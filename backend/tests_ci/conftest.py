"""Put backend/ on sys.path so `import app.<module>` resolves.

These tests deliberately import only torch-free modules (url_guard, schemas,
report_generator, job_store) so CI never needs the inference stack.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
