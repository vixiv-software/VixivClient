import requests
import json
import os
from pathlib import Path
import numpy as np
import pickle
import trimesh

class VixivClient:
    """Python client for the Vixiv API."""
    
    def __init__(self, api_key=None, api_url=None, base_url=None, debug=False):
        """Initialize the client with API key and URL.
        
        Args:
            api_key (str, optional): API key for authentication. If not provided, will look for VIXIV_API_KEY environment variable
            api_url (str, optional): Base URL of the API. If not provided, will look for VIXIV_API_URL environment variable
            base_url (str, optional): Alias for api_url, maintained for backward compatibility
        """
        self.api_key = api_key or os.getenv('VIXIV_API_KEY')
        self.debug = debug
        if not self.api_key:
            raise ValueError("API key must be provided either directly or through VIXIV_API_KEY environment variable")
        
        # Handle both api_url and base_url for backward compatibility
        self.api_url = api_url or base_url or os.getenv('VIXIV_API_URL', 'https://vixiv-flask-api-gcp-523287772169.us-central1.run.app')
        self.session = requests.Session()
        self.session.headers.update({'X-API-Key': self.api_key})
   
    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make a request to the API."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
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
            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"Response status code: {response.status_code}")
            print(f"Response error: {response.json()['error']}")
            print(f"Response traceback: {response.json()['traceback']}")
            raise

    def voxelize_mesh(
            self,
            file_path: str,
            network_path: str,
            cell_type: str = "fcc",
            cell_size: tuple = (40, 40, 40),
            beam_diameter: float = 2.0,
            offsets: np.ndarray = None,
            force_dir: tuple = (0, 0, 1),
            min_skin_thickness: float = 0.01,
            invert_cells: bool = True,
            cell_centers: np.ndarray = None,
            zero_thickness_dir: str = 'x',
            device: str='cpu',
        ) -> str:
        """Voxelize a mesh file and save the result."""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            if not file_path.lower().endswith('.stl'):
                raise ValueError("Only STL files are supported")

            # Prepare form data
            data = {
                'cell_type': cell_type,
                'cell_size': f"{cell_size[0]},{cell_size[1]},{cell_size[2]}",
                'beam_diameter': str(beam_diameter),
                'force_dir': f"{force_dir[0]},{force_dir[1]},{force_dir[2]}",
                'min_skin_thickness': str(min_skin_thickness),
                'offsets': json.dumps(offsets.tolist() if hasattr(offsets, 'tolist') else offsets),
                'cell_centers': json.dumps(cell_centers.tolist() if hasattr(cell_centers, 'tolist') else cell_centers),
                'zero_thickness_dir': zero_thickness_dir,
                'device': device,
            }

            # Upload and process the file
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
                response = self.session.request('POST', f"{self.api_url}/voxelize", files=files, data=data)
            
            if response.headers.get('success'):
                buf = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:  # filter out keep-alive chunks
                        buf.extend(chunk)

                # 3. Deserialize back into two arrays
                arr1, arr2 = pickle.loads(buf)
                trimesh.Trimesh(arr1, arr2).export(network_path)
                return network_path
            print(response.headers)
            raise ValueError(response.headers.get('error', 'Unknown error occurred'))

        except Exception as e:
            print(f"Error during voxelization: {str(e)}")
            raise

    def get_mesh_voxels(
            self,
            file_path: str,
            cell_size: tuple = (40, 40, 40),
            min_skin_thickness: float = 0.01,
            sampling_res: tuple = (1, 1, 1),
            force_dir: tuple = (0, 0, 1),
        ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Get voxels data from a mesh file using the specified parameters.
        
        Args:
            file_path: Path to the input STL file
            cell_size: Size of the cells in mm (tuple of x,y,z values)
            min_skin_thickness: Minimum skin thickness in mm
            sampling_res: Sampling resolution in xyz directions
            force_dir: Force direction vector for unit cell orientation
            
        Returns:
            tuple containing (location_table, offsets, cell_centers)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not file_path.lower().endswith('.stl'):
            raise ValueError("Only STL files are supported")
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
            
            data = {
                'cell_size': f"{cell_size[0]},{cell_size[1]},{cell_size[2]}",
                'min_skin_thickness': str(min_skin_thickness),
                'sampling_res': f"{sampling_res[0]},{sampling_res[1]},{sampling_res[2]}",
                'force_dir': f"{force_dir[0]},{force_dir[1]},{force_dir[2]}"
            }
            
            response = self._make_request('POST', 'get-mesh-voxels', files=files, data=data)
            
            if response.get('success'):
                result = response['result']
                return (
                    np.array(result['location_table']),
                    np.array(result['offsets']),
                    np.array(result['cell_centers'])
                )
            raise ValueError(response.get('error', 'Unknown error occurred'))
         
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
        
    def get_voxel_centers(
            self,
            cell_centers: list[tuple[float]],
            force_dir: tuple = (0, 0, 1),
            rotation_point: list[float]=(0, 0, 0),
        ) -> tuple[np.ndarray, float]:
        """Rotates all cell centers about the rotation point

        Args:
            cell_centers (list[tuple[float]]): center positions of unit cells
            force_dir (list[float]): direction of the applied force
            rotation_point (list[float]): point to rotate cell centers about

        Returns:
            np.ndarray: rotated cell centers
            float: angle of rotation
        """
        data = {
            'cell_centers': cell_centers.tolist() if isinstance(cell_centers, np.ndarray) else cell_centers,
            'force_dir': list(force_dir),
            'rotation_point': rotation_point.tolist() if isinstance(rotation_point, np.ndarray) else rotation_point
        }
        
        response = self._make_request('POST', 'get-voxel-centers', json=data)
        
        if response.get('success'):
            result = response['result']
            return (
                np.array(result['centers']),
                float(result['angle'])
            )
        raise ValueError(response.get('error', 'Unknown error occurred'))

    def generate_shader(
            self, 
            cell_type: str, 
            cell_size: tuple[float, float, float], 
            beam_diameter: float,
            cell_centers: np.ndarray, 
            shader_path: str, 
            view_normals: bool = False, 
            aa_passes: int = 0, 
            angle: float = 0.0,
            rotation_point: tuple[float]=(0, 0, 0),
            force_dir: tuple[float]=(0, 0, 1),
        ) -> None:
        """Generate a OpenGL shader to visualize voxel arrangement in real time.

        Args:
            cell_type (str): cell type, either 'fcc', 'bcc', or 'flourite'
            cell_size (tuple[float]): dimensions of unit cell
            beam_diameter (float): diameter of cell beam
            positions (tuple[tuple[float]]): list of 3d coordinates defining center positions of voxel cells
            out_path (str): path to save shader output
            view_normals (bool, optional): View normals of surface, instead of smooth shading. Defaults to False.
            aa_passes (int, optional): number of anti-aliasing passes when rendering a frame. Defaults to 0.
        """
        # Prepare request data
        data = {
            'cell_type': cell_type,
            'cell_size': cell_size,
            'beam_diameter': beam_diameter,
            'cell_centers': cell_centers.tolist(),
            'view_normals': view_normals,
            'aa_passes': aa_passes,
            'angle': angle,
            'rotation_point': rotation_point,
            'force_dir': force_dir,
        }

        # Create directory if it doesn't exist
        shader_dir = os.path.dirname(shader_path)
        if shader_dir:
            os.makedirs(shader_dir, exist_ok=True)

        # Make request
        response = self._make_request('POST', 'generate-shader', json=data)

        # Save shader content to file
        with open(shader_path, 'w') as f:
            f.write(response['shader_content'])

    def cell_volume(self, cell_type: str, beam_radius: float, cell_size: tuple[float, float, float]) -> float:
        data = {
            'cell_type': cell_type,
            'beam_radius': beam_radius,
            'cell_size': cell_size,
        }
        response = self._make_request('POST', 'cell_volume', json=data)
        if response.get('success'):
            return response.get('volume')
        raise ValueError(response.get('error', 'Unknown error occurred'))
   
    def get_status(self) -> dict:
        """Get the current status of the API.
        
        Returns:
            dict: API status information including rate limiting and state management status
        """
        return self._make_request('GET', 'status')