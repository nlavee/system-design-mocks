# SDXPY Archive Exercises

This repository contains implementations of exercises from the "SDXPY Archive" series by third-bit.com. Each exercise focuses on different aspects of system design and low-level coding, particularly relevant for Staff+ level software engineering interviews.

## Exercises

Here's a list of the exercises and their current implementation status:

1.  **SEQUENCING BACKUPS**: Modify the backup program so that manifests are numbered sequentially (00000001.csv, 00000002.csv).
    *   Status: Pending

2.  **JSON MANIFESTS**:
    *   Modify `backup.py` to save JSON manifests based on a command-line flag.
    *   Write `migrate.py` to convert CSV to JSON manifests.
    *   Modify `backup.py` to store username in manifests and `migrate.py` to transform old files.
    *   Status: Pending

3.  **MOCK HASHES**:
    *   Modify `backup.py` to use a function called `ourHash`.
    *   Create a replacement that returns some predictable value, such as the first few characters of the data.
    *   Rewrite the tests to use this function.
    *   Status: Pending

4.  **COMPARING MANIFESTS**: Write `compare-manifests.py` that reads two manifest files and reports changes.
    *   Status: Pending

5.  **FROM ONE STATE TO ANOTHER**:
    *   Write `from_to.py` that takes a directory and a manifest file as command-line arguments, then restores the state.
    *   Write some tests for `from_to.py` using `pytest` and a mock filesystem.
    *   Status: Pending

6.  **FILE HISTORY**:
    *   Write `file_history.py` that takes the name of a file and displays its history through available manifests.
    *   Write tests for `file_history.py` using `pytest` and a mock filesystem.
    *   Status: Pending

7.  **PRE-COMMIT HOOKS**: Modify `backup.py` to load and run a function called `pre_commit` from a file called `pre_commit.py`.
    *   Status: Pending
