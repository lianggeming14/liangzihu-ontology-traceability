"""Non-secret sample configuration and strictly local test-database guards."""
from dataclasses import dataclass
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'fish_review_10pct_v1'
DEFAULT_CONFIG = ROOT / 'config/fish-review.example.json'


@dataclass(frozen=True)
class ReviewConfig:
    source_archive: Path
    extracted_root: Path
    source_manifest: Path
    env_file: Path
    review_schema: str
    output_dir: Path


def load_config(path=DEFAULT_CONFIG, *, root=ROOT):
    """Resolve paths relative to the checkout, never the shell or config folder.

    No input files or environment variables are read here. In particular, a
    valid offline plan does not need credentials, a running DB, or ownership.json.
    """
    root = Path(root).resolve()
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    fields = {'source_archive', 'extracted_root', 'source_manifest', 'env_file',
              'review_schema', 'output_dir'}
    if not isinstance(value, dict) or set(value) != fields | {'contract'}:
        raise ValueError('Config must contain only the documented non-secret fields')
    if value['contract'] != 'fish-review-config/1' or value['review_schema'] != SCHEMA:
        raise ValueError('Only the fixed fish_review_10pct_v1 review schema is supported')
    paths = {}
    for key in fields - {'review_schema'}:
        item = value[key]
        if not isinstance(item, str) or not item.strip() or '://' in item:
            raise ValueError('Config paths must be local file paths, never URLs or credentials')
        paths[key] = (root / item).resolve()
    if paths['source_archive'] != paths['source_manifest'].parent / 'source.zip':
        raise ValueError('source_archive must be source.zip beside source_manifest for full byte verification')
    # Keep credential files outside tracked project paths. Existing private
    # dotenv files can contain other platform settings; only two keys are read.
    if not paths['env_file'].is_relative_to(root / '.runtime'):
        raise ValueError('env_file must be a private file beneath this checkout .runtime')
    return ReviewConfig(**paths, review_schema=SCHEMA)


def database_url(config):
    """Use an explicit file, never inherited settings or deployment activation."""
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    if not config.env_file.is_file():
        raise ValueError('Private env_file is missing; --plan does not require it')
    values = dotenv_values(config.env_file, interpolate=False)
    raw = values.get('LZO_GIS_MIGRATION_DATABASE_URL')
    try:
        url = make_url(raw)
        valid = (values.get('APP_ENV') == 'test'
                 and url.drivername == 'postgresql+psycopg'
                 and url.host == '127.0.0.1' and url.port is not None
                 and url.database == 'lzo_gis' and url.username == 'lzo_gis_owner'
                 and bool(url.password) and not url.query)
    except Exception:
        # URL parser errors may contain credentials; never propagate their text.
        raise ValueError('Invalid private GIS database configuration') from None
    if not valid:
        raise ValueError('APP_ENV=test and a loopback lzo_gis_owner/lzo_gis psycopg URL without query options are required')
    return raw


def require_empty_schema(connection):
    from sqlalchemy import text
    exists = connection.execute(text('SELECT to_regnamespace(:schema)'), {'schema': SCHEMA}).scalar_one()
    if exists is not None:
        raise ValueError('Review schema already exists; refusing overwrite; use --verify')
