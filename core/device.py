import uuid, os, hashlib

def get_machine_code():
    raw = f"{uuid.getnode()}-{os.environ.get('COMPUTERNAME','')}"
    return hashlib.sha256(raw.encode()).hexdigest()
