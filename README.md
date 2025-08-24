## AWS Labs EC2 Dashboard (Flask + Pipenv)

A simple Flask UI that lists EC2 instances across multiple AWS accounts, grouped by the `lab` tag. Each lab is collapsible and shows instance details. The header shows your active config file path. Errors are displayed if the config is missing/invalid or an AWS call fails.

### Prerequisites
- Python 3.11 installed and on PATH
- Pipenv installed (`pip install --user pipenv`)

### Setup
1. Open PowerShell and navigate to this folder:
   - `cd C:\proj\aws_gui`
2. Install dependencies:
   - `pipenv install`

### Configuration
- Edit `accounts.json` and add one object per account in this form:
```json
[
  {
    "name": "example-account",
    "ak": "AKIA...",
    "sk": "wJalrXUtnFEMI/K7MDENG/bPxRfiCY...",
    "region": "us-east-1"
  }
]
```
- To use a different config path, set the environment variable before starting the app:
  - PowerShell: `setx ACCOUNTS_CONFIG_PATH "C:\\path\\to\\your\\accounts.json"`
  - Then open a new PowerShell window so the change takes effect.

Required IAM permissions per account: at minimum `ec2:DescribeInstances`.

### Run
- Start the app:
  - `pipenv run start`
- Or activate the shell and run manually:
  - `pipenv shell`
  - `python app.py`

The server runs at `http://localhost:5000`.

### Notes
- Instances are grouped by the `lab` tag. Items without that tag appear under `(no lab tag)`.
- Counts show "Powered up" (state `running`) and "Total" instances per lab.
- Basic concurrency is used to speed up multi-account queries.
- Never commit real access keys; rotate regularly. Prefer short-lived credentials in production.
