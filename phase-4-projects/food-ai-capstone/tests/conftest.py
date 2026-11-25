import os
import tempfile

test_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{test_dir.name}/test.db"
os.environ["GEMINI_API_KEY"] = ""
