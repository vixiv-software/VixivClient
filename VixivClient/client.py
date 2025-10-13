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

class VixivClient:
    """Python client for the Vixiv API."""

    packing_endpoints = ['/pack-voxels', '/get-visualization-data', '/cell-volume', '/packing-api-status']
    meshing_endpoints = ['/meshing-api-status', '/accelerators', '/generate-mesh']
    
    def __init__(self, api_key: str=None, packing_api_url: str=None, meshing_api_url: str=None, id: str="anon", debug=False):
        """Initialize the client with API key and URLs.
        
        Args:
            api_key (str, optional): API key for authentication. If not provided, will look for VIXIV_API_KEY environment variable
            packing_api_url (str, optional): API url for packing. If not specified cannot use packing functionality.
            meshing_api_url (str, optional): API url for meshing. If not specified cannot use meshing functionality.
            id (str, optional): Unique user ID. Defaults to 'anon'
            debug (bool, optional). Whether to make verbose API calls. Defaults to False.
        """
        self.id = id
        self.api_key = api_key or os.getenv('VIXIV_API_KEY')
        self.debug = debug
        if not self.api_key:
            raise ValueError("API key must be provided either directly or through VIXIV_API_KEY environment variable")
        
        # Handle both api_url and base_url for backward compatibility
        self.packing_api_url = "" if packing_api_url is None else packing_api_url + "/api/v1"
        self.meshing_api_url = "" if meshing_api_url is None else meshing_api_url + "/api/v1"
        self.session = requests.Session()
        self.session.headers.update({'X-API-Key': self.api_key, "id": self.id})
   
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

        # prepare files and make request
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
                print(f"   Error: {response.headers.get("error")}")
                print(f"   Traceback: {response.headers.get("traceback")}")
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
            # prepare files
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
            
            # make request
            response = self._make_request("POST", '/get-visualization-data', files=files)

            # collect result
            if response.json().get("success", False):
                data = response.json()
                results = {}
                results['cell_size'] = np.array(data['cell_size'])
                results['cell_centers'] = np.array(data['cell_centers'])
                results['rotation_matrix'] = np.array(data['rotation_matrix'])
                results['rotation_point'] = np.array(data['rotation_point'])
                all_centers = np.array(data['candidate_centers'])
                all_rotated_centers = (all_centers - results['rotation_point']) @ results['rotation_matrix'].T
                full_arr = np.concat([all_rotated_centers + results['rotation_point'], results['cell_centers']], axis=0)
                results['partial_centers'] = np.unique(full_arr, axis=0)
                return results
            else:
                if self.debug:
                    print(f"Error calling /get-visualization-data:")
                    print(f"   Error: {response.headers.get("error")}")
                    print(f"   Traceback: {response.headers.get("traceback")}")
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
            # prepare files
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
            
            # prepare data
            data = {
                "cell_type": cell_type,
                "beam_diameter": beam_diameter,
                "conformal": conformal,
            }
            if clear_direction is not None:
                data["clear_direction"] = clear_direction

            # make request
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
                    print(f"   Error: {response.headers.get("error")}")
                    print(f"   Traceback: {response.headers.get("traceback")}")
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