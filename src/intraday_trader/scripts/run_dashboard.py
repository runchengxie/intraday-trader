import subprocess
import sys
from pathlib import Path


def main():
    """
    This is the command-line entry point. Its only job is to launch the
    Streamlit server process, pointing it to the actual dashboard script.
    """
    try:
        package_dir = Path(__file__).resolve().parent.parent
        dashboard_script_path = (package_dir / "dashboard_app.py").resolve()

        if not dashboard_script_path.exists():
            print(
                f"Error: Dashboard app script not found at '{dashboard_script_path}'",
                file=sys.stderr,
            )
            sys.exit(1)

        command = ["streamlit", "run", str(dashboard_script_path)]
        print(f"Executing command: {' '.join(command)}")
        subprocess.run(command, check=False)

    except Exception as e:
        print(f"Error launching dashboard: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
