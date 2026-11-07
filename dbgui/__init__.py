"""Database admin GUI for IndeedHelper.

Layers:
    data.py       - all SQL + format preservation
    migrations.py - users.homePage -> job_searches
    workspace.py  - per-user bot folder + Chrome profile, created on demand
    server.py     - Flask JSON API
Launched by db_admin.py at the repo root.
"""
