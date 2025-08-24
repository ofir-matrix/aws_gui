import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, render_template, request


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(APP_ROOT, "accounts.json")


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        accounts_config_path = os.environ.get("ACCOUNTS_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        accounts, config_errors = load_accounts_config(accounts_config_path)

        labs_to_instances, errors = fetch_all_accounts_grouped_by_lab(accounts)
        summary = summarize_labs(labs_to_instances)
        overall = compute_overall_counts(summary)

        return render_template(
            "index.html",
            labs_to_instances=labs_to_instances,
            summary=summary,
            overall=overall,
            errors=config_errors + errors,
            messages=[],
            accounts_path=accounts_config_path,
        )

    @app.route("/labs/stop", methods=["POST"])
    def stop_lab():
        target_lab = (request.form.get("lab_name") or "").strip()
        accounts_config_path = os.environ.get("ACCOUNTS_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        accounts, config_errors = load_accounts_config(accounts_config_path)

        errors: List[str] = []
        messages: List[str] = []

        if not target_lab:
            errors.append("Lab name is required.")
        else:
            # Collect running instance IDs per account for the target lab
            per_account_ids: List[Tuple[Dict[str, Any], List[str]]] = []

            def collect_task(acct: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
                try:
                    instances = fetch_instances_for_account(acct)
                    ids = [
                        i["instance_id"]
                        for i in instances
                        if (i.get("lab") or "(no lab tag)") == target_lab and i.get("state") == "running"
                    ]
                    return acct["name"], ids, []
                except Exception as exc:  # noqa: BLE001
                    return acct.get("name", "unknown"), [], [f"{acct.get('name', 'unknown')}: {exc}"]

            with ThreadPoolExecutor(max_workers=min(8, max(1, len(accounts)))) as executor:
                futures = {executor.submit(collect_task, acct): acct for acct in accounts}
                for future in as_completed(futures):
                    acct_name, ids, acct_errs = future.result()
                    errors.extend(acct_errs)
                    # Match back to full account dict
                    if ids:
                        per_account_ids.append((futures[future], ids))
                        messages.append(f"{acct_name}: stopping {len(ids)} instance(s) in lab '{target_lab}'")

            # Perform stop per account
            for acct, instance_ids in per_account_ids:
                try:
                    stop_instances_for_account(acct, instance_ids)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{acct.get('name', 'unknown')}: stop failed: {exc}")

        # Recompute current view
        labs_to_instances, fetch_errors = fetch_all_accounts_grouped_by_lab(accounts)
        summary = summarize_labs(labs_to_instances)
        overall = compute_overall_counts(summary)
        errors.extend(config_errors + fetch_errors)

        return render_template(
            "index.html",
            labs_to_instances=labs_to_instances,
            summary=summary,
            overall=overall,
            errors=errors,
            messages=messages,
            accounts_path=accounts_config_path,
        )

    @app.route("/labs/start", methods=["POST"])
    def start_lab():
        target_lab = (request.form.get("lab_name") or "").strip()
        accounts_config_path = os.environ.get("ACCOUNTS_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        accounts, config_errors = load_accounts_config(accounts_config_path)

        errors: List[str] = []
        messages: List[str] = []

        if not target_lab:
            errors.append("Lab name is required.")
        else:
            # Collect stopped instance IDs per account for the target lab
            per_account_ids: List[Tuple[Dict[str, Any], List[str]]] = []

            def collect_task(acct: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
                try:
                    instances = fetch_instances_for_account(acct)
                    ids = [
                        i["instance_id"]
                        for i in instances
                        if (i.get("lab") or "(no lab tag)") == target_lab and i.get("state") == "stopped"
                    ]
                    return acct["name"], ids, []
                except Exception as exc:  # noqa: BLE001
                    return acct.get("name", "unknown"), [], [f"{acct.get('name', 'unknown')}: {exc}"]

            with ThreadPoolExecutor(max_workers=min(8, max(1, len(accounts)))) as executor:
                futures = {executor.submit(collect_task, acct): acct for acct in accounts}
                for future in as_completed(futures):
                    acct_name, ids, acct_errs = future.result()
                    errors.extend(acct_errs)
                    if ids:
                        per_account_ids.append((futures[future], ids))
                        messages.append(f"{acct_name}: starting {len(ids)} instance(s) in lab '{target_lab}'")

            # Perform start per account
            for acct, instance_ids in per_account_ids:
                try:
                    start_instances_for_account(acct, instance_ids)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{acct.get('name', 'unknown')}: start failed: {exc}")

        # Recompute current view
        labs_to_instances, fetch_errors = fetch_all_accounts_grouped_by_lab(accounts)
        summary = summarize_labs(labs_to_instances)
        overall = compute_overall_counts(summary)
        errors.extend(config_errors + fetch_errors)

        return render_template(
            "index.html",
            labs_to_instances=labs_to_instances,
            summary=summary,
            overall=overall,
            errors=errors,
            messages=messages,
            accounts_path=accounts_config_path,
        )

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


def load_accounts_config(config_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    if not os.path.exists(config_path):
        errors.append(f"Config file not found at {config_path}. Provide a JSON file with a list of accounts.")
        return [], errors

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON in {config_path}: {exc}"]

    if not isinstance(data, list):
        return [], ["Config must be a JSON array of accounts objects."]

    normalized_accounts: List[Dict[str, Any]] = []
    for idx, acct in enumerate(data):
        if not isinstance(acct, dict):
            errors.append(f"Account entry #{idx + 1} must be an object.")
            continue

        name = acct.get("name")
        access_key_id = acct.get("ak")
        secret_access_key = acct.get("sk")
        region_name = acct.get("region")

        missing_fields = [
            field_name
            for field_name, value in [
                ("name", name),
                ("ak", access_key_id),
                ("sk", secret_access_key),
                ("region", region_name),
            ]
            if not value
        ]
        if missing_fields:
            errors.append(
                f"Account '{name or f'#'+str(idx+1)}' missing fields: {', '.join(missing_fields)}"
            )
            continue

        normalized_accounts.append(
            {
                "name": str(name),
                "ak": str(access_key_id),
                "sk": str(secret_access_key),
                "region": str(region_name),
            }
        )

    return normalized_accounts, errors


def fetch_all_accounts_grouped_by_lab(accounts: List[Dict[str, Any]]) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    labs_to_instances: Dict[str, List[Dict[str, Any]]] = {}
    errors: List[str] = []

    def task(account: Dict[str, Any]) -> Tuple[str, Dict[str, List[Dict[str, Any]]], List[str]]:
        try:
            instances = fetch_instances_for_account(account)
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for instance in instances:
                lab_name = instance.get("lab") or "(no lab tag)"
                grouped.setdefault(lab_name, []).append(instance)
            return account["name"], grouped, []
        except Exception as exc:  # noqa: BLE001
            return account.get("name", "unknown"), {}, [f"{account.get('name', 'unknown')}: {exc}"]

    # Use modest concurrency to avoid overwhelming API or local machine.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(accounts)))) as executor:
        futures = {executor.submit(task, account): account for account in accounts}
        for future in as_completed(futures):
            _, grouped_result, acct_errors = future.result()
            # Merge grouped results on the main thread
            for lab_name, instances in grouped_result.items():
                labs_to_instances.setdefault(lab_name, []).extend(instances)
            errors.extend(acct_errors)

    # Sort instances in each lab by account then by instance id for stable display
    for lab_name, instances in labs_to_instances.items():
        instances.sort(key=lambda x: (x.get("account"), x.get("instance_id")))

    # Sort labs alphabetically
    labs_to_instances = dict(sorted(labs_to_instances.items(), key=lambda item: item[0].lower()))

    return labs_to_instances, errors


def fetch_instances_for_account(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    session = boto3.session.Session(
        aws_access_key_id=account["ak"],
        aws_secret_access_key=account["sk"],
        region_name=account["region"],
    )

    client = session.client(
        "ec2",
        config=BotoConfig(
            retries={"max_attempts": 10, "mode": "standard"},
            user_agent_extra="aws-gui-labs/1.0",
        ),
    )

    paginator = client.get_paginator("describe_instances")

    instances: List[Dict[str, Any]] = []

    try:
        for page in paginator.paginate(PaginationConfig={"PageSize": 1000}):
            reservations = page.get("Reservations", [])
            for reservation in reservations:
                for ec2 in reservation.get("Instances", []):
                    instances.append(transform_instance(account["name"], ec2))
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(f"Error fetching EC2 instances in {account['name']} ({account['region']}): {exc}")

    return instances


def stop_instances_for_account(account: Dict[str, Any], instance_ids: List[str]) -> None:
    if not instance_ids:
        return

    session = boto3.session.Session(
        aws_access_key_id=account["ak"],
        aws_secret_access_key=account["sk"],
        region_name=account["region"],
    )
    client = session.client(
        "ec2",
        config=BotoConfig(
            retries={"max_attempts": 10, "mode": "standard"},
            user_agent_extra="aws-gui-labs/1.0",
        ),
    )

    # AWS allows up to 50 instance IDs per StopInstances call
    chunk_size = 50
    for i in range(0, len(instance_ids), chunk_size):
        chunk = instance_ids[i : i + chunk_size]
        try:
            client.stop_instances(InstanceIds=chunk, Force=False)
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"stop_instances failed in {account['name']} ({account['region']}): {exc}")


def start_instances_for_account(account: Dict[str, Any], instance_ids: List[str]) -> None:
    if not instance_ids:
        return

    session = boto3.session.Session(
        aws_access_key_id=account["ak"],
        aws_secret_access_key=account["sk"],
        region_name=account["region"],
    )
    client = session.client(
        "ec2",
        config=BotoConfig(
            retries={"max_attempts": 10, "mode": "standard"},
            user_agent_extra="aws-gui-labs/1.0",
        ),
    )

    chunk_size = 50
    for i in range(0, len(instance_ids), chunk_size):
        chunk = instance_ids[i : i + chunk_size]
        try:
            client.start_instances(InstanceIds=chunk)
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"start_instances failed in {account['name']} ({account['region']}): {exc}")


def transform_instance(account_name: str, ec2: Dict[str, Any]) -> Dict[str, Any]:
    tags = {tag.get("Key"): tag.get("Value") for tag in ec2.get("Tags", []) if tag.get("Key")}

    instance_state = (ec2.get("State", {}) or {}).get("Name", "unknown")

    transformed = {
        "account": account_name,
        "instance_id": ec2.get("InstanceId"),
        "name": tags.get("Name", ""),
        "state": instance_state,
        "type": ec2.get("InstanceType"),
        "az": (ec2.get("Placement", {}) or {}).get("AvailabilityZone"),
        "public_ip": ec2.get("PublicIpAddress"),
        "private_ip": ec2.get("PrivateIpAddress"),
        "lab": tags.get("lab"),
    }
    return transformed


def summarize_labs(labs_to_instances: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for lab_name, instances in labs_to_instances.items():
        total = len(instances)
        powered_up = sum(1 for i in instances if i.get("state") == "running")
        account_names = sorted({i.get("account") for i in instances if i.get("account")})
        summary[lab_name] = {"total": total, "powered_up": powered_up, "accounts": account_names}
    return summary


def compute_overall_counts(summary: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    total = sum(v.get("total", 0) for v in summary.values())
    powered_up = sum(v.get("powered_up", 0) for v in summary.values())
    off = total - powered_up
    return {"total": total, "powered_up": powered_up, "off": off}


if __name__ == "__main__":
    application = create_app()
    # Use 0.0.0.0 to be accessible locally if needed; change port via PORT env var.
    port = int(os.environ.get("PORT", 5000))
    application.run(host="0.0.0.0", port=port, debug=True)
