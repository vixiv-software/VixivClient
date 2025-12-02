# VixivClient

Interact with Vixiv's core computational geometry toolkit.

## Installation

```bash
pip install git+https://github.com/vixiv-software/VixivClient.git
```

## Minimal Example

```python
from VixivClient.client import VixivClient

# initialize the client
client = VixivClient(
    api_key="", 
    packing_api_url="https://packing.com",
    meshing_api_url="https://meshing.com",
)

# test the status of each API
print(client.get_packing_status())
print(client.get_meshing_status())

# set parameters for workflow
mesh_path = "test.stl"
cell_size = 20
skin_thickness = 1
network_direction = [0, 0, 1]
beam_diameter = 3
cell_type = "bcc"
clear_type = 'x'
conformal = False

# get the packing information of the part with the requested parameters
packing_data = client.pack_voxels(
    mesh_path=mesh_path,
    cell_size=cell_size,
    skin_thickness=skin_thickness,
    network_direction=network_direction,
)

# generate a mesh file with the desired parameters
mesh = client.generate_mesh(
    voxelization_data=packing_data,
    cell_type=cell_type,
    beam_diameter=beam_diameter,
    clear_direction=clear_type,
    conformal=conformal,
)
mesh.export("completed_mesh.stl")
```

## Client Methods

### `pack_voxels(mesh_path, cell_size, skin_thickness, network_direction, seed_point, optimize_packing, user_id, project_id)`
Calculate optimal placement of cells within the specified geometry.

Arguments
- mesh_path: string or Path specifying the target geometry to calculate placement of cells
- cell_size: float or tuple[float] specifying the size of the cells
- skin_thickness: float specifying the desired minimum thickness between the outer skin of the input part and any placed cells
- network_direction: tuple[float] detailing the z direction the unit cell local orientation should align with
- seed_point: tuple[float], where to place voxel centerfor beginning of tiling for voxel packing. If None, infers best choice. Defaults to None.
- optimize_packing: bool, whether to optimize voxel placement for the most number of voxels while preserving symmetry, otherwise uses seed point. Defaults to True.
- user_id: int, unique user ID to associate with this API call. Defaults to anonymous (-1)
- project_id: str, user-scoped unique project identifer to associate with this API call. Defaults to no project ("")

Returns
- bytes: raw binary data of voxelization results. Save to disk using ".vox" suffix as best practice

### `get_visualization_data(voxelization_data, cell_type, beam_thickness, user_id, project_id)`
Get voxel placement data from the voxelization results binary file.

Arguments
- voxelization_data: bytes, str, or Path object containing data recieved from pack_voxels method, either raw (directly from `pack_voxels` method) or filepath
- cell_type: str, type of unit cell. Choose 'bcc', 'fcc', or 'fluorite'
- beam_thickness: float, diameter of the unit cell beam, mm
- user_id: int, unique user ID to associate with this API call. Defaults to anonymous (-1)
- project_id: str, user-scoped unique project identifer to associate with this API call. Defaults to no project ("")

Returns
- dict[str, np.ndarray]: numpy arrays containing relevant data to visualize cells before meshing. Keys include:
    - 'cell_size': (3,) array of the size of the cell packed
    - 'cell_centers': (N, 3) array of the locations of all full voxels
    - 'partial_centers': (M, 3) array of the locations of any potential voxels that overlap with the target geometry, but are not fully within it. NOTE: cells contained in this list are not guaranteed to overlap with target geometry
    - 'rotation_matrix': (3, 3) array describing rotation from the global coordinate system to the local unit cell coordinate system
    - 'rotation_point': (3,) array describing the point at which the centers/input mesh should be rotated about (if desired)

### `generate_mesh(voxelization_data, cell_type, beam_diameter, clear_direction, conformal, user_id, project_id)`
Generate the optimized part as a triangular surface mesh using precomputed packing data.

Arguments:
- voxelization_data: bytes, str, or Path object containing data recieved from pack_voxels method, either raw (directly from `pack_voxels` method) or filepath
- cell_type: str describing the desired cell to be placed at each voxel location. Choose from 'bcc', 'fcc', or 'fluorite'
- beam_diameter: float, diameter of beam for unit cell
- clear_direction: str, whether to allow for material unpacking automatically. Choose from 'x', 'y', or None to omit this process
- conformal: bool, True to allow partial cells that conform to the geometry of the input part, False to only consider full cells
- user_id: int, unique user ID to associate with this API call. Defaults to anonymous (-1)
- project_id: str, user-scoped unique project identifer to associate with this API call. Defaults to no project ("")

Returns:
- trimesh.Trimesh: trimesh object containing the optimized part as a triangular surface mesh

### `mesh_center(file_path)`
Calculate the center of mass for a triangular surface mesh.

Arguments:
- file_path: str, the filepath of the surface mesh

Returns:
- np.ndarray: (3,) array, the center of mass

### `cell_volume(cell_type, beam_radius, cell_size, user_id, project_id)`
Calculate the volume of a unit cell with the desired properties

Arguments:
- cell_type: str describing the desired cell to be placed at each voxel location. Choose from 'bcc', 'fcc', 'fluorite', or 'acs'
- beam_radius: float, radius of the beam for the unit cell
- cell_size: float or list[float] describing the dimensions of the unit cell bounding box
- user_id: int, unique user ID to associate with this API call. Defaults to anonymous (-1)
- project_id: str, user-scoped unique project identifer to associate with this API call. Defaults to no project ("")

Returns:
-  float: volume of the unit cell

### `get_packing_status()`
Get information on the status of the packing API

Returns:
- json object containing API information

### `get_meshing_status()`
Get information on the status of the meshing API

Returns:
- json object containing API information

### `get_meshing_accelerators()`
Get information on the availible hardware for the meshing API

Returns:
- json object containing API hardware information

### `upload_file_to_bucket(local_path)`
Upload a local file to the temporary incoming file google cloud storage bucket. Requires the client machine to be authenticated with Vixiv's cloud deployment backend (internal use only).

Arguments
- local_path: string or Path specifying where on the client machine the file to upload is located.

Returns
- str: the URI for the uploaded file

## Environment Variables

- `VOXELIZE_API_KEY`: Your API key for authentication, used if api key is not specified upon client initialization
