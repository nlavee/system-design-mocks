# backup.py
#
# This file implements a simple file archiver based on the concepts
# presented in "SDXPY Archive" from third-bit.com, Chapter 10.
# It focuses on hashing file contents to avoid duplication and
# creating manifests for snapshots.

import glob
import csv
import shutil
import time
from pathlib import Path
from hashlib import sha256
import json # Added for JSON manifest support

# Define the length of the truncated hash code.
# This is a simplification for display purposes and not recommended for
# real-world version control systems due to increased collision risk.
HASH_LEN = 16

def hash_all(root_dir):
    """
    Finds all files within a given root directory and its subdirectories,
    calculates a truncated SHA256 hash for each file's content,
    and returns a list of (filename, hash_code) tuples.

    Args:
        root_dir (str): The root directory to start hashing from.

    Returns:
        list: A list of tuples, where each tuple contains the relative
              path of a file and its truncated SHA256 hash.
    """
    result = []
    # Using glob with recursive=True to find all files.
    # The root_dir argument tells glob to search within that directory
    # and return paths relative to it.
    for name in glob.glob("**/*.*", root_dir=root_dir, recursive=True):
        full_name = Path(root_dir, name)
        # Ensure we only process actual files and not directories
        if full_name.is_file():
            with open(full_name, "rb") as reader:
                data = reader.read()
                # Calculate SHA256 hash and truncate it.
                hash_code = sha256(data).hexdigest()[:HASH_LEN]
                result.append((name, hash_code))
    return result

def current_time():
    """
    Returns the current UTC timestamp as a string, truncated to an integer.
    This helper function wraps `time.time()` to facilitate mocking in tests.
    It is used by the global `backup` function, but `ArchiveLocal` now uses
    sequential numbering for its manifests as part of an exercise.

    Returns:
        str: A string representation of the current UTC timestamp (integer part).
    """
    # Truncating to an integer string simplifies manifest naming.
    # The original article suggests this for simplicity, but it can lead
    # to race conditions if multiple backups happen within the same second.
    return f"{time.time()}".split(".")[0]

def write_manifest(backup_dir, manifest_id, manifest):
    """
    Writes the manifest (list of files and their hashes) to a CSV file
    within the backup directory. The filename is based on the provided manifest_id
    (which could be a timestamp or a sequence number).

    Args:
        backup_dir (str): The directory where backup files and manifests are stored.
        timestamp (str): The timestamp used to name the manifest file.
        manifest (list): A list of (filename, hash_code) tuples.
    """
    backup_dir_path = Path(backup_dir)
    # Ensure the backup directory exists, creating it if necessary.
    # This check can introduce a race condition if multiple processes try
    # to create the directory simultaneously.
    if not backup_dir_path.exists():
        backup_dir_path.mkdir(parents=True, exist_ok=True) # parents=True creates any necessary parent directories, exist_ok=True prevents an error if the directory already exists (mitigating one aspect of the race condition for mkdir itself).

    manifest_file = Path(backup_dir_path, f"{manifest_id}.csv")
    with open(manifest_file, "w", newline='') as raw: # newline='' is important for csv module to handle line endings correctly
        writer = csv.writer(raw)
        writer.writerow(["filename", "hash"]) # Write CSV header
        writer.writerows(manifest) # Write all manifest entries

def write_json_manifest(backup_dir, manifest_id, manifest):
    """
    Writes the manifest (list of files and their hashes) to a JSON file
    within the backup directory. The filename is based on the provided manifest_id.

    Args:
        backup_dir (str): The directory where backup files and manifests are stored.
        manifest_id (str): The ID (timestamp or sequence number) used to name the manifest file.
        manifest (list): A list of (filename, hash_code) tuples.
    """
    backup_dir_path = Path(backup_dir)
    if not backup_dir_path.exists():
        backup_dir_path.mkdir(parents=True, exist_ok=True)

    manifest_file = Path(backup_dir_path, f"{manifest_id}.json")
    # Convert manifest list of tuples to a list of dictionaries for better JSON readability
    manifest_data = [{"filename": item[0], "hash": item[1]} for item in manifest]
    with open(manifest_file, "w") as writer:
        json.dump(manifest_data, writer, indent=4) # Use indent for pretty-printing JSON

def copy_files(source_dir, backup_dir, manifest):
    """
    Copies unique files from the source directory to the backup directory
    based on the provided manifest. Files are named by their hash code.
    Only copies a file if a backup with that hash doesn't already exist.

    Args:
        source_dir (str): The directory containing the original files.
        backup_dir (str): The directory where backup files are stored.
        manifest (list): A list of (filename, hash_code) tuples.
    """
    for (filename, hash_code) in manifest:
        source_path = Path(source_dir, filename)
        backup_path = Path(backup_dir, f"{hash_code}.bck")
        # Check if the backup file already exists to avoid redundant copies.
        # This check is another potential race condition: a file might be
        # created by another process between the exists() check and a potential copy.
        if not backup_path.exists():
            shutil.copy(source_path, backup_path)

def backup(source_dir, backup_dir):
    """
    Performs a backup operation: hashes all files in the source directory,
    creates a timestamped manifest, and copies unique files to the backup directory.

    Args:
        source_dir (str): The directory to back up.
        backup_dir (str): The destination directory for backups.

    Returns:
        list: The manifest created during this backup operation.
    """
    manifest = hash_all(source_dir)
    timestamp = current_time()
    write_manifest(backup_dir, timestamp, manifest)
    copy_files(source_dir, backup_dir, manifest)
    return manifest

# --- Refactored Archive Classes (Top-Down Design / Successive Refinement) ---
# The article introduces a refactoring to use a base class 'Archive'
# and a derived class 'ArchiveLocal' for better extensibility and
# abstraction, aligning with object-oriented principles.

class Archive:
    """
    Base class for archival operations.
    Prescribes the general steps for creating a backup, but delegates
    specific implementation details (like writing manifests and copying files)
    to concrete derived classes.
    This adheres to the Open/Closed Principle (OCP): open for extension,
    closed for modification.
    """
    def __init__(self, source_dir, manifest_format="csv"):
        # The directory containing the files to be archived.
        self._source_dir = source_dir
        # The format for the manifest files (e.g., "csv" or "json").
        self._manifest_format = manifest_format

    def backup(self):
        """
        Performs the high-level backup process.
        Steps: hash files, write manifest, copy files.
        This method defines the template for the backup process.
        """
        manifest = hash_all(self._source_dir)
        # These methods are intended to be implemented by derived classes.
        self._write_manifest(manifest)
        self._copy_files(manifest)
        return manifest

    # These methods are placeholders (or abstract methods in a more formal OOP sense)
    # that concrete Archive implementations must override.
    def _write_manifest(self, manifest):
        """
        Placeholder for writing the manifest.
        Must be implemented by a derived class.
        """
        raise NotImplementedError

    def _copy_files(self, manifest):
        """
        Placeholder for copying files.
        Must be implemented by a derived class.
        """
        raise NotImplementedError


    """
    Concrete implementation of Archive for local file system backups.
    Re-uses the previously defined functions for writing manifests and copying files.
    This demonstrates how object-oriented programming allows old code to
    use new code (e.g., a new archival strategy) without modification,
    by adhering to the interface defined by the base class.
    """
    def __init__(self, source_dir, backup_dir):
        super().__init__(source_dir)
        # Specific to local archiving: the destination backup directory.
        self._backup_dir = backup_dir
        # For sequential backups, determine the next sequence number instead of using a timestamp.
        # This replaces the timestamp logic for manifest naming as per the "Sequencing Backups" exercise.
        # However, it introduces a Time-of-Check to Time-of-Use (TOCTOU) race condition in multi-process
        # environments, as multiple processes could determine the same 'next' sequence number
        # simultaneously before one of them creates the file.
        self._sequence_number = self._get_next_sequence_number()

    def _write_manifest(self, manifest):
        """
        Implements manifest writing for local storage using the global `write_manifest` function.
        It uses the generated sequence number for the manifest filename, adhering to the
        "Sequencing Backups" exercise requirement.
        """
        # The manifest filename is now based on the sequential number.
        write_manifest(self._backup_dir, self._sequence_number, manifest)

    def _copy_files(self, manifest):
        """
        Implements file copying for local storage using the global `copy_files` function.
        """
        copy_files(self._source_dir, self._backup_dir, manifest)

    def _get_next_sequence_number(self):
        """
        Determines the next sequential manifest number by scanning the backup directory.
        Looks for files named 'NNNNNNNN.csv', extracts the highest number, and returns
        it incremented by one, formatted as an 8-digit string.
        This method is vulnerable to a Time-of-Check to Time-of-Use (TOCTOU) race condition:
        if multiple processes call this simultaneously, they might all get the same
        "next" number, leading to file conflicts.

        Returns:
            str: The next sequence number formatted as an 8-digit string (e.g., "00000001").
        """
        backup_dir_path = Path(self._backup_dir)
        if not backup_dir_path.exists():
            return "00000001" # Start with 1 if directory doesn't exist

        # Find all existing manifest files with the sequential naming convention
        # Using glob with root_dir for relative path matching
        manifest_files = [f.name for f in backup_dir_path.glob("********.csv") if f.is_file()]
        
        max_sequence = 0
        for file_name in manifest_files:
            try:
                # Extract the numeric part of the filename (e.g., "00000001" from "00000001.csv")
                sequence_str = Path(file_name).stem
                sequence_num = int(sequence_str)
                if sequence_num > max_sequence:
                    max_sequence = sequence_num
            except ValueError:
                # Ignore files that don't match the expected numeric format
                continue
        
        next_sequence = max_sequence + 1
        return f"{next_sequence:08d}" # Format as an 8-digit string with leading zeros

# Example of how to use ArchiveLocal (as hinted in the article)
# if __name__ == "__main__":
#    import sys
#    if len(sys.argv) != 3:
#        print("Usage: python backup.py <source_directory> <backup_directory>")
#        sys.exit(1)
#    source_dir = sys.argv[1]
#    backup_dir = sys.argv[2]
#    print(f"Backing up '{source_dir}' to '{backup_dir}'...")
#    archiver = ArchiveLocal(source_dir, backup_dir)
#    archiver.backup()
#    print("Backup complete.")
