"""
scripts/backup_restore.py — Herramienta para Respaldar y Restaurar datos de SmartWMS
Permite crear un backup de la base de datos sqlite en un solo archivo con timestamp
o restaurarlo fácilmente.
"""

import os
import shutil
import sys
from datetime import datetime

script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)
db_source = os.path.join(root_dir, "ecommerce.db")
backups_dir = os.path.join(root_dir, "backups")

def backup():
    if not os.path.exists(db_source):
        print(f"[ERROR] No se encontro la base de datos en {db_source}")
        return False

    os.makedirs(backups_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backups_dir, f"ecommerce_backup_{timestamp}.db")
    
    shutil.copy2(db_source, backup_file)
    size_kb = os.path.getsize(backup_file) / 1024.0
    print(f"[OK] Respaldo creado exitosamente:")
    print(f"     Archivo: {backup_file}")
    print(f"     Tamano:  {size_kb:.1f} KB")
    return True

def restore(target_file=None):
    if not target_file:
        if not os.path.exists(backups_dir):
            print("[ERROR] No se encontro la carpeta de respaldos 'backups'.")
            return False
        
        backups = sorted([f for f in os.listdir(backups_dir) if f.endswith(".db")])
        if not backups:
            print("[ERROR] No hay respaldos disponibles en la carpeta 'backups'.")
            return False
        target_file = os.path.join(backups_dir, backups[-1]) # El mas reciente

    if not os.path.exists(target_file):
        print(f"[ERROR] El archivo de respaldo no existe: {target_file}")
        return False

    # Copiar a la raiz y a backend
    shutil.copy2(target_file, db_source)
    backend_db = os.path.join(root_dir, "ecommerce", "backend", "ecommerce.db")
    if os.path.exists(os.path.dirname(backend_db)):
        shutil.copy2(target_file, backend_db)

    print(f"[OK] Base de datos restaurada correctamente desde:")
    print(f"     {target_file} -> {db_source}")
    return True

def list_backups():
    if not os.path.exists(backups_dir):
        print("[INFO] La carpeta 'backups' aun no existe.")
        return
    files = sorted([f for f in os.listdir(backups_dir) if f.endswith(".db")])
    if not files:
        print("[INFO] No se encontraron archivos de respaldo en 'backups/'.")
        return
    print(f"Respaldos disponibles ({len(files)}):")
    for f in files:
        fpath = os.path.join(backups_dir, f)
        kb = os.path.getsize(fpath) / 1024.0
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  - {f} ({kb:.1f} KB, modificado: {mtime})")

if __name__ == "__main__":
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "backup"
    if action == "backup":
        backup()
    elif action == "restore":
        param = sys.argv[2] if len(sys.argv) > 2 else None
        restore(param)
    elif action == "list":
        list_backups()
    else:
        print("Uso: python backup_restore.py [backup|restore|list] [ruta_archivo_opcional]")
