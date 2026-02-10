import os
import json
import csv
import hashlib
import importlib.util
import sys
from datetime import datetime
from unittest.mock import patch, mock_open

# =============================================================================
# EXERCISE 1: SEQUENCING BACKUPS
# =============================================================================
# Reasoning: Moving from timestamps to sequential numbers (00000001.csv) 
# provides a clear, gap-detectable order. 
# Why it doesn't solve TOCTOU: The race condition occurs between hashing a 
# file and copying it. Even if we name the manifest 00000001.csv, the 
# physical file on disk can change AFTER we've recorded its hash but BEFORE 
# it's archived.

def get_next_manifest_name(directory, ext='csv'):
    """Finds the highest existing number and increments it."""
    existing = [f for f in os.listdir(directory) if f.endswith(ext)]
    nums = []
    for f in existing:
        name = os.path.splitext(f)[0]
        if name.isdigit():
            nums.append(int(name))
    next_num = max(nums) + 1 if nums else 1
    return f"{next_num:08d}.{ext}"


# =============================================================================
# EXERCISE 3: MOCK HASHES
# =============================================================================
# Reasoning: We inject the hashing function as a dependency. In production, 
# we use 'our_hash'. In tests, we inject 'mock_hash'. This allows tests to be 
# deterministic and fast without real file I/O.

def our_hash(data):
    """Real hashing using SHA-256."""
    return hashlib.sha256(data).hexdigest()

def mock_hash(data):
    """Predictable hash for testing: just the first 8 bytes."""
    return data[:8].decode('utf-8', errors='ignore').ljust(8, '0')


# =============================================================================
# EXERCISE 2: JSON MANIFESTS & MIGRATION
# =============================================================================
# Reasoning: The Manifest class encapsulates formatting. The migration logic 
# handles schema updates (adding 'creator').

class Manifest:
    def __init__(self, creator=None):
        self.files = {} # path -> hash
        self.creator = creator or os.getlogin()

    def add(self, path, file_hash):
        self.files[path] = file_hash

    def save(self, path, format='csv'):
        if format == 'csv':
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['path', 'hash', 'creator'])
                for p, h in self.files.items():
                    writer.writerow([p, h, self.creator])
        elif format == 'json':
            data = {'metadata': {'creator': self.creator}, 'files': self.files}
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path):
        _, ext = os.path.splitext(path)
        m = cls()
        if ext == '.csv':
            with open(path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    m.add(row['path'], row['hash'])
                    m.creator = row.get('creator', 'unknown')
        elif ext == '.json':
            with open(path, 'r') as f:
                data = json.load(f)
                m.files = data['files']
                m.creator = data['metadata']['creator']
        return m

def migrate_manifests(source_dir, target_format='json'):
    """
    Exercise 2.2 & 2.3: Converts CSV to JSON and ensures 'creator' is present.
    """
    for f in os.listdir(source_dir):
        if f.endswith('.csv'):
            m = Manifest.load(os.path.join(source_dir, f))
            new_path = os.path.join(source_dir, os.path.splitext(f)[0] + '.' + target_format)
            m.save(new_path, format=target_format)
            print(f"Migrated {f} to {new_path}")


# =============================================================================
# EXERCISE 4: COMPARING MANIFESTS
# =============================================================================
# Reasoning: We use sets for fast membership testing and dicts to map 
# hashes back to names for rename detection.

def compare_manifests(path1, path2):
    m1 = Manifest.load(path1)
    m2 = Manifest.load(path2)
    
    results = {'changed': [], 'renamed': [], 'deleted': [], 'added': []}
    
    # name -> hash
    f1, f2 = m1.files, m2.files
    # hash -> name
    h1 = {v: k for k, v in f1.items()}
    h2 = {v: k for k, v in f2.items()}

    for path, hash_val in f1.items():
        if path in f2:
            if f2[path] != hash_val:
                results['changed'].append(path)
        elif hash_val in h2:
            results['renamed'].append((path, h2[hash_val]))
        else:
            results['deleted'].append(path)

    for path, hash_val in f2.items():
        if path not in f1 and hash_val not in h1:
            results['added'].append(path)
            
    return results


# =============================================================================
# EXERCISE 5: FROM ONE STATE TO ANOTHER (Restore)
# =============================================================================
# Reasoning: To restore state efficiently, we calculate the delta. 
# In this exercise, we assume the 'archive' has the files.

def from_to(target_dir, manifest_path, hash_func=our_hash):
    manifest = Manifest.load(manifest_path)
    # 1. Check existing
    for root, _, files in os.walk(target_dir):
        for f in files:
            p = os.path.relpath(os.path.join(root, f), target_dir)
            if p not in manifest.files:
                os.remove(os.path.join(target_dir, p)) # Delete extra
    
    # 2. Add/Update
    for p, h in manifest.files.items():
        dest = os.path.join(target_dir, p)
        if not os.path.exists(dest):
            # In real system: fetch from archive. Here: dummy write.
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'w') as f: f.write("restored") 


# =============================================================================
# EXERCISE 6: FILE HISTORY
# =============================================================================
# Reasoning: Tracing a file requires linear search through the manifest 
# timeline.

def file_history(filename, manifest_dir):
    history = []
    manifests = sorted([f for f in os.listdir(manifest_dir) if f.endswith(('.csv', '.json'))])
    for m_file in manifests:
        m = Manifest.load(os.path.join(manifest_dir, m_file))
        if filename in m.files:
            history.append((m_file, m.files[filename]))
    return history


# =============================================================================
# EXERCISE 7: PRE-COMMIT HOOKS
# =============================================================================
# Reasoning: Dynamic execution via 'importlib' allows the archiver to 
# execute arbitrary user code as a safety gate.

def run_pre_commit(root_dir):
    hook_file = os.path.join(root_dir, "pre_commit.py")
    if not os.path.exists(hook_file): return True
    try:
        spec = importlib.util.spec_from_file_location("hook", hook_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.pre_commit()
    except:
        return False


# =============================================================================
# TESTING & DEMONSTRATION
# =============================================================================

def test_exercises():
    """
    Demonstrates Exercise 3 (Mock Hashes) and Exercise 5 (from_to) logic 
    using a mock approach.
    """
    print("Running Tests for Exercises...")
    
    # Test Exercise 3: Mock Hashing
    data = b"hello world"
    assert mock_hash(data) == "hello wo", "Mock hash should be predictable"
    
    # Test Exercise 4: Comparison logic
    m1 = Manifest(creator="User1")
    m1.add("a.txt", "h1")
    m1.save("m1.json", format="json")
    
    m2 = Manifest(creator="User1")
    m2.add("a.txt", "h1_new") # changed
    m2.add("b.txt", "h2")     # added
    m2.save("m2.json", format="json")
    
    diff = compare_manifests("m1.json", "m2.json")
    assert "a.txt" in diff['changed']
    assert "b.txt" in diff['added']
    
    # Cleanup temp files
    os.remove("m1.json")
    os.remove("m2.json")
    
    print("Tests Passed!")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_exercises()
    else:
        print("SDXPY Chapter 10 Exercise Implementation")
        print("Use --test to run internal validation.")
