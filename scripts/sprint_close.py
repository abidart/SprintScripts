import os
import re
from typing import Any, Dict, List, Union

import asana
from dotenv import load_dotenv

# supports pre-fixes with up two numbers. Let's hope we never have to use them
DUPLICATED_TASK_PREFIX = re.compile(r"^\[(?P<number>[0-9]{0,2})\]")


def get_duplicate_name(name: str) -> str:
    """
    Return the name of a duplicated task. For example:

    get_duplicate_name("Hello") -> "[1] Hello"
    get_duplicate_name("[2] World") -> [3] World"

    :param name: the name of the old task
    :return: the name of the new task
    """

    match = DUPLICATED_TASK_PREFIX.match(name)
    if match is None:
        return f"[1] {name}"
    prefix = f"[{(int(match.group('number')) + 1)}]"
    return f"{prefix} {name[4:]}"


def generate_memberships(
    task: Dict[str, Any], sprints_project_gid: str, backlog_gid: str
) -> List[Dict[str, str]]:
    """
    Generate the `memberships` payload for the duplicate task.

    :param task: the task we want to replicate
    :param sprints_project_gid: the GID of the Asana Sprints project
    :param backlog_gid: the GID of the backlog section in the Asana Sprints project
    :return: the `memberships` field payload for a post request
    """

    raw = task["memberships"]
    memberships: List[Dict[str, str]] = []
    for membership in raw:
        if membership["project"]["gid"] == sprints_project_gid:
            memberships.append({"project": sprints_project_gid, "section": backlog_gid})
        else:
            memberships.append(
                {
                    "project": membership["project"]["gid"],
                    "section": membership["section"]["gid"],
                }
            )
    return memberships


def generate_custom_fields(
    task: Dict[str, Any],
    expected_field_gid: str,
    actual_field_gid: str,
    sprint_number_field_gid: str,
) -> Dict[str, Union[str, int]]:
    """
    Generate the `custom_fields` payload for the duplicate task.

    :param task: the task to be duplicated
    :param expected_field_gid: the GID of the field with the expected cost of a task
    :param actual_field_gid: the GID of the field with the cost of a task
    :param sprint_number_field_gid: the GID of the field that stores the Sprint number
    :return: the `custom fields` field payload for a post request
    """

    raw = task["custom_fields"]
    custom_fields: Dict[str, Union[str, int]] = dict()
    expected = 0
    actual = 0

    for custom_field in raw:
        # TODO: improve these clauses
        if custom_field["gid"] == expected_field_gid:
            if custom_field["number_value"] is None:
                continue
            expected = custom_field["number_value"]
        elif custom_field["gid"] == actual_field_gid:
            if custom_field["number_value"] is None:
                continue
            actual = custom_field["number_value"]
        elif custom_field["gid"] == sprint_number_field_gid:
            continue
        elif custom_field["type"] == "enum":
            if custom_field["enum_value"] is None:
                continue
            custom_fields[custom_field["gid"]] = custom_field["enum_value"]["gid"]
        elif custom_field["type"] == "text":
            custom_fields[custom_field["gid"]] = custom_field["text_value"]
        elif custom_field["type"] == "number":
            custom_fields[custom_field["gid"]] = custom_field["number_value"]
        else:
            assert False, "Something did not work as expected."

    custom_fields[expected_field_gid] = expected - actual if actual < expected else 0
    return custom_fields


def duplicate_tasks(
    asana_client: asana.client.Client,
    workspace_gid: str,
    sprints_project_gid: str,
    backlog_gid: str,
    section_gid: str,
    expected_field_gid: str,
    actual_field_gid: str,
    sprint_number_field_gid: str,
) -> None:
    """
    Duplicate tasks that have not been completed during the last
    Sprint.

    :param asana_client: the asana client that manages communication
    with the Asana API
    :param workspace_gid: the GID of the Asana workspace
    :param sprints_project_gid: the GID of the Asana Sprints project
    :param backlog_gid: the GID of the backlog section in the Asana Sprints project
    :param section_gid: the GID of the section whose tasks we want to duplicate
    :param expected_field_gid: the GID of the field with the expected cost of a task
    :param actual_field_gid: the GID of the field with the cost of a task
    :param sprint_number_field_gid: the GID of the field that stores the Sprint number
    """

    section = asana_client.tasks.get_tasks(
        params={"section": section_gid},
        opt_fields=[
            "name",
            "custom_fields",
            "memberships.section.gid",
            "memberships.project.gid",
            "assignee",
        ],
    )

    for task in section:
        task_gid, task_name, task_assignee = (
            task["gid"],
            get_duplicate_name(task["name"]),
            task["assignee"],
        )
        task_memberships = generate_memberships(
            task=task, sprints_project_gid=sprints_project_gid, backlog_gid=backlog_gid
        )

        task_custom_fields = generate_custom_fields(
            task=task,
            expected_field_gid=expected_field_gid,
            actual_field_gid=actual_field_gid,
            sprint_number_field_gid=sprint_number_field_gid,
        )

        task = {
            "name": task_name,
            "assignee": task_assignee,
            "memberships": task_memberships,
            "custom_fields": task_custom_fields,
        }

        asana_client.tasks.create_in_workspace(workspace_gid, task)
        client.tasks.delete_task(task_gid=task_gid)


def complete_tasks(asana_client: asana.Client, section_gid: str) -> None:
    """
    Mark as complete the tasks that have been completed during the last Sprint.

    :param asana_client: the asana client that manages communication
    with the Asana API
    :param section_gid: the GID of the section whose tasks we want to mark as complete
    """

    section = asana_client.tasks.get_tasks(params={"section": section_gid},)

    for task in section:
        task_gid = task["gid"]
        asana_client.tasks.update_task(task_gid, {"completed": True})


if __name__ == "__main__":
    # TODO: switch to environ-config
    load_dotenv()
    ASANA_TOKEN = os.environ["ASANA_TOKEN"]

    # WORKSPACE
    WORKSPACE_GID = os.environ["BENDING_SPOONS_GID"]

    # PROJECT
    SPRINTS_PROJECT_GID = os.environ["TEST_SPRINTS_GID"]

    # SECTIONS
    BACKLOG_GID = os.environ["TEST_BACKLOG_GID"]
    DONE_GID = os.environ["TEST_DONE_GID"]
    # this list holds the GIDs of sections with tasks that need to be duplicated
    # NOTE: I did not use list comprehension because the autocompletion is very helpful
    OTHER_GIDS = [
        os.environ["TEST_SPRINT_BACKLOG_GID"],
        os.environ["TEST_IN_PROGRESS_GID"],
        os.environ["TEST_BLOCKED_GID"],
        os.environ["TEST_UNDER_REVIEW_GID"],
    ]

    # CUSTOM FIELDS
    EXPECTED_FIELD_GID = os.environ["EXPECTED_COST_FIELD_GID"]
    ACTUAL_FIELD_GID = os.environ["ACTUAL_COST_FIELD_GID"]
    SPRINT_NUMBER_FIELD_GID = os.environ["SPRINT_NUBER_FIELD_GID"]

    client = asana.Client.access_token(accessToken=ASANA_TOKEN)

    # duplicate tasks in each of the non-completed sections
    for gid in OTHER_GIDS:
        duplicate_tasks(
            asana_client=client,
            workspace_gid=WORKSPACE_GID,
            sprints_project_gid=SPRINTS_PROJECT_GID,
            backlog_gid=BACKLOG_GID,
            section_gid=gid,
            expected_field_gid=EXPECTED_FIELD_GID,
            actual_field_gid=ACTUAL_FIELD_GID,
            sprint_number_field_gid=SPRINT_NUMBER_FIELD_GID,
        )

    # mark as done tasks that were completed
    complete_tasks(asana_client=client, section_gid=DONE_GID)
