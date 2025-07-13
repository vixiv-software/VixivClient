# VixivClient

The main class for interacting with the Vixiv API.

## Installation

#### Via private Vixiv PyPi

If you have a Vixiv google cloud account, you can directly install this library via pip. First, ensure you are logged into your account:

```bash
gcloud auth application-default login
```

Then, point pip to search the private Vixiv PyPi repository when installing packages. This does not remove the primary default location for pip to find libraries.

```bash
pip config set global.extra-index-url https://us-central1-python.pkg.dev/vixiv-geometry-backend/vixiv-internal-libraries/simple/
```

Finally, install the library via pip

```bash
pip install VixivClient
```

#### Via Vixiv github

If you do not have a vixiv google cloud account, you can install directly from github:

```bash
pip install git+https://github.com/vixiv-software/VIXIV-FLASK-API.git
```

## Methods

TODO: update method documentation

- `voxelize_mesh(file_path, cell_type=None, cell_size=None, beam_diameter=None, scale_factor=None)`
- `generate_shader(cell_type, positions, scale_factor=None)`
- `calculate_voxel_centers(cell_type, cell_size, angle=None)`
- `get_status()`

## Environment Variables

- `VOXELIZE_API_KEY`: Your API key for authentication

## Push to private Vixiv PyPi

## Uploading to Artifact Registry

Uploading package wheel to a google artifact repository allows this library to be easily and securely installed on GCP. If you have not yet setup an artifact registry for this library, jump to the next section to setup.

When the library source is updated, run the following command to rebuild the wheel (run from the root directory where pyproject.toml is located):

```bash
python -m build --wheel --outdir dist
```

Then upload the new wheel to the repository:

```bash
python -m twine upload --repository-url https://us-central1-python.pkg.dev/vixiv-geometry-backend/vixiv-internal-libraries/ dist/* --skip-existing
```

If you are prompted for password, kill the command and run the following to set the default credentials, then try uploading again:

```bash
gcloud auth application-default login
```

## Creating Artifact Registry

If an artifact repository has not yet been created in the project, run the following command:

```bash
gcloud artifacts repositories create vixiv-internal-libraries --repository-format=python --location=us-central1 --description="Private python library wheels"
```

If twine and the google keyring plugin is not installed, run the following command:

```bash
pip install --upgrade twine keyrings.google-artifactregistry-auth
```

Then run this command to activate the application default credentials:

```bash
gcloud auth application-default login
```