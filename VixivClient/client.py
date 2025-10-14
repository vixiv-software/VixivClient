import requests
import json
import os
from pathlib import Path
import numpy as np
import trimesh
import io
from uuid import uuid4
from tempfile import NamedTemporaryFile
import traceback
from google.cloud import storage
from google.auth import credentials

class VixivClient:
    """Python client for the Vixiv API."""

    packing_endpoints = ['/pack-voxels', '/get-visualization-data', '/cell-volume', '/packing-api-status']
    meshing_endpoints = ['/meshing-api-status', '/accelerators', '/generate-mesh']
    bucket_name = "geometry-backend-temp-uploads"
    upload_dir = "incoming"
    upload_chunk_size = 8 * 1024 * 1024     # must be multiple of 256 kb
    
    def __init__(self, api_key: str=None, packing_api_url: str=None, meshing_api_url: str=None, id: str="anon", gcloud_creds: credentials.Credentials=None, use_bucket: bool=True, debug=False):
        """Initialize the client with API key and URLs.
        
        Args:
            api_key (str, optional): API key for authentication. If not provided, will look for VIXIV_API_KEY environment variable
            packing_api_url (str, optional): API url for packing. If not specified cannot use packing functionality.
            meshing_api_url (str, optional): API url for meshing. If not specified cannot use meshing functionality.
            id (str, optional): Unique user ID. Defaults to 'anon'
            gcloud_creds (credentials.Credentials, optional): OAuth credentials to access GCS, if not provided uses env. Defaults to None.
            use_bucket (bool, optional): Whether to upload files to bucket to perform request, only False for testing backwards compatability. Defaults to True.
            debug (bool, optional). Whether to make verbose API calls. Defaults to False.
        """
        self.id = id
        self.api_key = api_key or os.getenv('VIXIV_API_KEY')
        self.debug = debug
        if not self.api_key:
            raise ValueError("API key must be provided either directly or through VIXIV_API_KEY environment variable")
        
        self.packing_api_url = "" if packing_api_url is None else packing_api_url + "/api/v1"
        self.meshing_api_url = "" if meshing_api_url is None else meshing_api_url + "/api/v1"
        self.session = requests.Session()
        self.session.headers.update({'X-API-Key': self.api_key, "id": self.id})
        if not isinstance(gcloud_creds, credentials.Credentials): gcloud_creds = None
        self.bucket = storage.Client(credentials=gcloud_creds).bucket(self.bucket_name)
        self.use_bucket = use_bucket
   
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make a request to the API."""
        packing = endpoint in self.packing_endpoints
        meshing = endpoint in self.meshing_endpoints
        if not packing and not meshing:
            raise ValueError("Requested endpoint is not associated with a known API")
        if packing and meshing:
            raise ValueError("Requested enpoint is associated with multiple known APIs, call is ambiguous")
        api_url = self.packing_api_url if packing else self.meshing_api_url
        url = f"{api_url}/{endpoint.lstrip('/')}"

        if self.debug:
            print(f"Making request to: {url}")
            print(f"Method: {method}")
            print(f"Headers: {self.session.headers}")
            if 'data' in kwargs:
                print(f"Form data: {kwargs['data']}")
            if 'files' in kwargs:
                print(f"Files: {[f for f in kwargs['files'].keys()]}")
        
        # Remove Content-Type header for multipart file uploads
        headers = self.session.headers.copy()
        if 'files' in kwargs:
            headers.pop('Content-Type', None)
            kwargs['headers'] = headers
        
        response = self.session.request(method, url, **kwargs)
        
        if response.status_code == 429:
            raise ValueError("Rate limit exceeded. Please try again later.")
        elif response.status_code == 401:
            raise ValueError("Invalid API key")
        
        try:
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            print(f"Response status code: {response.status_code}")
            print(f"Response error: {response.json()['error']}")
            print(f"Response traceback: {response.json()['traceback']}")
            raise

    def _has_bucket_privileges(self) -> bool:
        """Check whether this client has permission to upload files to gcs bucket.

        Returns:
            bool: True if the client has permission, otherwise False.
        """
        roles = ["storage.objects.create"]
        granted = self.bucket.test_iam_permissions(roles)
        for role in roles:
            if role not in granted:
                return False
        return True

    def upload_file_to_bucket(self, local_path: str | Path) -> str:
        """Upload a file to GCP bucket. Deletion is handled on the 
        google service consuming this resource, or lifecycle rule on bucket

        Args:
            local_path (str | Path): local file to upload

        Returns:
            str: link to bucket
        """
        upload_name = f"{uuid4()}{Path(local_path).suffix}"
        upload_path = f"{self.upload_dir}/{upload_name}"
        blob = self.bucket.blob(upload_path)
        blob.upload_from_filename(str(local_path), content_type="application/octet-stream")
        return f"gs://{self.bucket_name}/{upload_path}"

    def pack_voxels(
            self,
            mesh_path: str | Path,
            cell_size: float | tuple[float], 
            skin_thickness: float, 
            network_direction: tuple[float],
        ) -> bytes:
        """Find packing arrangements.

        Args:
            mesh_path (str | Path): path to mesh describing geometry to pack
            cell_size (float | tuple[float]): size of the individual voxel
            skin_thickness (float): desired distance between outer geometry and packed voxels
            network_direction (tuple[float]): which direction the voxel's local up direction should align with

        Returns:
            bytes: voxelization results. Recommended file extension to save is '.vox'
        """
        if isinstance(mesh_path, str):
            mesh_path = Path(mesh_path)

        # prepare data
        cell_size = [cell_size] * 3 if isinstance(cell_size, float | int) else cell_size
        data = {
            'cell_size': ",".join([str(i) for i in cell_size]),
            'skin_thickness': skin_thickness,
            'network_direction': ",".join([str(i) for i in network_direction]),
        }

        if self._has_bucket_privileges() and self.use_bucket:
            data['mesh_url'] = self.upload_file_to_bucket(mesh_path)
            response = self._make_request("POST", '/pack-voxels', data=data)
            print("Here!")
        else:
            files = {}
            with open(mesh_path, 'rb') as f:
                files['input_mesh.stl'] = (os.path.basename(mesh_path), f, 'application/octet-stream')
                response = self._make_request("POST", '/pack-voxels', files=files, data=data)

        # stream result
        if response.headers.get('success', False):
            buf = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    buf.extend(chunk)
            return bytes(buf)
        else:
            if self.debug:
                print(f"Error calling /pack-voxels:")
                print(f"   Error: {response.headers.get('error')}")
                print(f"   Traceback: {response.headers.get('traceback')}")
            return None
        
    def get_visualization_data(self, voxelization_data: bytes | str | Path) -> dict[str, np.ndarray]:
        """Collect visualization info needed to display solution on frontend. Partial centers contains 
            cells that could potentially be partial, but could lay totally outside geometry.

        Args:
            voxelization_data (bytes | str | Path): data recieved from pack_voxels method, either raw or filepath

        Returns:
            dict[str, np.ndarray]: 'cell_size': (3,) array, 'cell_centers': (N, 3) array, 'partial_centers': (M, 3) array, 
                'rotation_matrix': (3, 3) array, 'rotation_point': (3,) array
        """
        temp_file = None
        try:
            if self._has_bucket_privileges() and self.use_bucket:
                if isinstance(voxelization_data, bytes):
                    temp_file = NamedTemporaryFile(delete_on_close=False, delete=False, suffix=".vox")
                    temp_file.write(voxelization_data)
                    temp_file.seek(0)
                    url = self.upload_file_to_bucket(temp_file.name)
                elif isinstance(voxelization_data, Path) or isinstance(voxelization_data, str):
                    url = self.upload_file_to_bucket(voxelization_data)
                response = self._make_request("POST", '/get-visualization-data', data={"results_url": url})
            else:
                files = {}
                if isinstance(voxelization_data, bytes):
                    temp_file = NamedTemporaryFile(delete_on_close=False, delete=False, suffix=".vox")
                    temp_file.write(voxelization_data)
                    temp_file.seek(0)
                    files['voxelization_results.vox'] = (os.path.basename(temp_file.file.name), temp_file, 'application/octet-stream')
                elif isinstance(voxelization_data, Path) or isinstance(voxelization_data, str):
                    temp_file = open(voxelization_data, 'rb')
                    files['voxelization_results.vox'] = (os.path.basename(voxelization_data), temp_file, 'application/octet-stream')
                else:
                    raise ValueError(f"Unsupported type {type(voxelization_data)} for voxelization_data")
                response = self._make_request("POST", '/get-visualization-data', files=files)

            # collect result
            if response.headers.get("success", False):
                results = {}
                buf = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        buf.extend(chunk)
                with np.load(io.BytesIO(bytes(buf))) as data:
                    results['cell_size'] = data['cell_size']
                    results['cell_centers'] = data['cell_centers']
                    results['rotation_matrix'] = data['rotation_matrix']
                    results['rotation_point'] = data['rotation_point']
                    all_centers = data['candidate_centers']
                    all_rotated_centers = (all_centers - results['rotation_point']) @ results['rotation_matrix'].T
                    full_arr = np.concat([all_rotated_centers + results['rotation_point'], results['cell_centers']], axis=0)
                    results['partial_centers'] = np.unique(full_arr, axis=0)
                    return results
            else:
                if self.debug:
                    print(f"Error calling /get-visualization-data:")
                    print(f"   Error: {response.headers.get('error')}")
                    print(f"   Traceback: {response.headers.get('traceback')}")
                return None
        except Exception as e:
            raise e
        finally:
            if temp_file is not None:
                temp_file.close()
                os.remove(temp_file.name)

    def generate_mesh(
            self,
            voxelization_data: bytes | str | Path, 
            cell_type: str,
            beam_diameter: float,
            clear_direction: str,
            conformal: bool,
        ) -> trimesh.Trimesh:
        """Generate optimized mesh

        Args:
            voxelization_data (bytes | str | Path): raw bytes or path to saved voxelization packing data
            cell_type (str): type of unit cell. Choose 'bcc', 'fcc', or 'fluorite'
            beam_diameter (float): diameter of the unit cell beam, mm
            clear_direction (str): direction to remove regions of skin for unpacking purposes. Choose 'x' or 'y' or None
            conformal (bool): Whether partial unit cells are allowed to be generated

        Returns:
            trimesh.Trimesh: surface mesh of optimized part
        """
        temp_file = None
        try:
            # prepare data
            data = {
                "cell_type": cell_type,
                "beam_diameter": beam_diameter,
                "conformal": conformal,
            }
            if clear_direction is not None:
                data["clear_direction"] = clear_direction

            if self._has_bucket_privileges() and self.use_bucket:
                if isinstance(voxelization_data, bytes):
                    with NamedTemporaryFile(delete_on_close=True, suffix=".vox") as f:
                        f.write(voxelization_data)
                        f.seek(0)
                        url = self.upload_file_to_bucket(f.name)
                elif isinstance(voxelization_data, Path) or isinstance(voxelization_data, str):
                    url = self.upload_file_to_bucket(voxelization_data)
                    data["results_url"] = url
                response = self._make_request("POST", "/generate-mesh", data=data)
            else:
                files = {}
                if isinstance(voxelization_data, bytes):
                    temp_file = NamedTemporaryFile(delete_on_close=False, delete=False, suffix=".vox")
                    temp_file.write(voxelization_data)
                    temp_file.seek(0)
                    files['voxelization_results.vox'] = (os.path.basename(temp_file.file.name), temp_file, 'application/octet-stream')
                elif isinstance(voxelization_data, Path) or isinstance(voxelization_data, str):
                    temp_file = open(voxelization_data, 'rb')
                    files['voxelization_results.vox'] = (os.path.basename(voxelization_data), temp_file, 'application/octet-stream')
                else:
                    raise ValueError(f"Unsupported type {type(voxelization_data)} for voxelization_data")
                response = self._make_request("POST", "/generate-mesh", files=files, data=data)

            # collect result
            if response.headers.get("success", False):
                buf = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        buf.extend(chunk)
                with np.load(io.BytesIO(bytes(buf))) as mesh_data:
                    voxelized_mesh = trimesh.Trimesh(mesh_data["part_verts"], mesh_data["part_tris"])
                return voxelized_mesh
            else:
                if self.debug:
                    print(f"Error calling /generate-mesh:")
                    print(f"   Error: {response.headers.get('error')}")
                    print(f"   Traceback: {response.headers.get('traceback')}")
                return None
        except Exception as e:
            raise e
        finally:
            if temp_file is not None:
                temp_file.close()
                os.remove(temp_file.name)
         
    def mesh_center(self, file_path: str) -> np.ndarray:
        """
        Read a mesh file and return its center point.
        
        Args:
            file_path: Path to the input STL file
            
        Returns:
            numpy.ndarray: The center point of the mesh
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not file_path.lower().endswith('.stl'):
            raise ValueError("Only STL files are supported")
        
        return trimesh.load_mesh(file_path).center_mass

    def cell_volume(self, cell_type: str, beam_radius: float, cell_size: float | list[float]) -> float:
        """Calculate the volume of a unit cell with the given dimensions

        Args:
            cell_type (str): type of unit cell. Choose 'bcc', 'fcc', or 'fluorite'
            beam_radius (float): radius of the cell beams in mm
            cell_size (float | list[float]): dimensions of the cell in mm

        Returns:
            float: volume of the cell, in mm^3
        """
        cell_size = [cell_size] * 3 if isinstance(cell_size, float | int) else cell_size
        data = {
            'cell_type': cell_type,
            'beam_radius': beam_radius,
            'cell_size': ",".join([str(i) for i in cell_size]),
        }
        response = self._make_request('POST', '/cell-volume', data=data)
        if response.json().get('success', False):
            return response.json().get('volume')
        raise ValueError(response.headers.get('error', 'Unknown error occurred'))
   
    def get_packing_status(self) -> dict:
        """Get the current status of the packing API.
        
        Returns:
            dict: API status information including rate limiting and state management status
        """
        return self._make_request('GET', '/packing-api-status').json()
    
    def get_meshing_status(self) -> dict:
        """Get the current status of the meshing API.
        
        Returns:
            dict: API status information including rate limiting and state management status
        """
        return self._make_request('GET', '/meshing-api-status').json()
    
    def get_meshing_accelerators(self) -> dict:
        """Get recognized acceleration devices for the meshing API.
        
        Returns:
            dict: API accelerator status and availible devices, including their hardware specifications
        """
        return self._make_request('GET', '/accelerators').json()