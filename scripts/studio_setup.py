"""Initialize Studio locally; show the private admin key only when requested."""
import argparse
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)
from backend.studio.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-key", action="store_true")
    args = parser.parse_args()
    store = Store()
    store.initialize()
    print("Studio initialized. Existing domain configurations were preserved.")
    print("Domains:", ", ".join(store.domains()))
    if args.show_key:
        print("\nPrivate administration key (do not commit, publish, or put in screenshots):")
        print(store.admin_key)
    print("\nStart from the project root:")
    print("python -m uvicorn backend.studio.app:app --host 127.0.0.1 --port 8000")
    print("Open http://127.0.0.1:8000/studio/")


if __name__ == "__main__":
    main()
