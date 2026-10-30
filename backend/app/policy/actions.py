from enum import StrEnum


class Action(StrEnum):
    # Spec §5
    MANAGE_FUTRAN_USERS = "manage_futran_users"
    VIEW_FUTRAN_USERS = "view_futran_users"
    CREATE_CLIENT_ENGAGEMENT = "create_client_engagement"
    APPROVE_ENGAGEMENT = "approve_engagement"
    VIEW_ENGAGEMENT = "view_engagement"
    ASSIGN_AUDITORS = "assign_auditors"
    MANAGE_CLIENT_USERS = "manage_client_users"
    VIEW_CLIENT_USERS = "view_client_users"
    CONFIGURE_TEMPLATES = "configure_templates"
    APPROVE_TEMPLATES = "approve_templates"
    REGISTER_AI_TOOL = "register_ai_tool"
    SUBMIT_USE_CASE = "submit_use_case"
    APPROVE_USE_CASE = "approve_use_case"
    PROPOSE_TIER = "propose_tier"
    SET_FINAL_TIER = "set_final_tier"
    OVERRIDE_FINAL_TIER = "override_final_tier"
    RECORD_NAMED_USERS = "record_named_users"
    LAUNCH_ATTESTATION = "launch_attestation"
    VIEW_INDIVIDUAL_ATTESTATIONS = "view_individual_attestations"
    VIEW_ATTESTATION_AGGREGATES = "view_attestation_aggregates"
    ANSWER_GOVERNANCE = "answer_governance"
    APPROVE_GOVERNANCE = "approve_governance"
    VIEW_GOVERNANCE = "view_governance"
    UPLOAD_EVIDENCE = "upload_evidence"
    VIEW_EVIDENCE = "view_evidence"
    RECORD_FINDINGS = "record_findings"
    APPROVE_FINDINGS = "approve_findings"
    SIGN_FINAL_REPORT = "sign_final_report"
    VIEW_FINAL_REPORT = "view_final_report"
    RESPOND_FINDINGS = "respond_findings"
    APPROVE_RESPONSES = "approve_responses"
    VIEW_FINDINGS_RESPONSES = "view_findings_responses"
    VERIFY_REMEDIATION = "verify_remediation"
    CLOSE_REMEDIATION = "close_remediation"
    VIEW_AUDIT_LOG = "view_audit_log"
    VIEW_INVENTORY = "view_inventory"
    # v0.2 and schematic
    PREFILL_SYSTEM = "prefill_system"
    VERIFY_SYSTEM_ANSWERS = "verify_system_answers"
    SCORE_SYSTEM = "score_system"
    VIEW_SCORES = "view_scores"
    MANAGE_DOCUMENT_REQUESTS = "manage_document_requests"
    UPLOAD_REQUESTED_DOCUMENT = "upload_requested_document"
    SIGN_DECLARATION = "sign_declaration"
    MANAGE_REFERENCE_DATA = "manage_reference_data"
    RUN_LAW_REFRESH = "run_law_refresh"
    APPROVE_SYSTEM_ADDITION = "approve_system_addition"
    MANAGE_SYSTEMS = "manage_systems"
    SIGN_CLIENT_SIGNOFF = "sign_client_signoff"
    ADVANCE_STAGE = "advance_stage"
    # attestation changes, 27 October
    SEND_ATTESTATION = "send_attestation"  # give every client user with a login an attestation line item
    COMPLETE_OWN_ATTESTATION = "complete_own_attestation"  # see and answer one's own line item
    MANAGE_ATTESTATION_ANSWERS = "manage_attestation_answers"  # mark reviewed, correct, remove individual answers
    # AI system register and governance roles (spec §24.7, §27.2)
    VIEW_REGISTER = "view_register"
    EDIT_REGISTER = "edit_register"  # add, edit, bulk edit and CSV import within scope
    IMPORT_INVENTORY_TO_REGISTER = "import_inventory_to_register"
    ADD_SYSTEM_LAW = "add_system_law"
    REMOVE_SYSTEM_LAW = "remove_system_law"  # removes directly and approves removals others ask for
    FILL_SYSTEM_ROLES = "fill_system_roles"
    SET_COMPANY_ROLES = "set_company_roles"
    MARK_REQUIRED_ROLE_NA = "mark_required_role_na"
    SUBMIT_GO_LIVE = "submit_go_live"
    APPROVE_GO_LIVE = "approve_go_live"
    MANAGE_COMMITTEE_MEMBERS = "manage_committee_members"
    RECORD_COMMITTEE = "record_committee"
    RECORD_SYSTEM_HISTORY = "record_system_history"
    # v0.6 WS-D: litigation (§27.4), opportunities (§27.5), client alerts (§27.6), refresh alerts (§27.9)
    VIEW_LITIGATION = "view_litigation"
    MANAGE_LITIGATION = "manage_litigation"  # add and edit cases, run the litigation refresh
    VIEW_OPPORTUNITIES = "view_opportunities"
    WORK_OPPORTUNITIES = "work_opportunities"  # add, log calls, proposals and outcomes, change stage and owner
    APPROVE_OPPORTUNITY = "approve_opportunity"  # approve an offer to a current audit client
    MANAGE_CLIENT_ALERTS = "manage_client_alerts"  # alert rules grid
    APPROVE_CLIENT_ALERTS = "approve_client_alerts"  # approve and send waiting client alerts
    APPROVE_ADDON_ALERTS = "approve_addon_alerts"  # the Sales owner approves tracing add-on alerts
    MANAGE_ALERT_SETTINGS = "manage_alert_settings"  # M6 refresh alert settings
