import zipfile
import os

def create_zip():
    companion_dir = 'companion'
    zip_path = os.path.join('browser_version', 'static', 'desktop-companion.zip')
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(companion_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if '__pycache__' not in file_path and not file.endswith('.zip') and 'venv' not in file_path:
                    arcname = os.path.relpath(file_path, start=companion_dir)
                    zipf.write(file_path, arcname)

if __name__ == '__main__':
    create_zip()
    print("Created desktop-companion.zip in browser_version/static/")
