"""The first-slice acceptance plan (005 S1.7) mapped to the tests that prove each case (S1-T8, GATE-S1).

Each case names test functions as "module::function", where every parametrized instance counts, or
one instance as "module::function[id]" where a case depends on that instance specifically. tests/conftest.py reports every case at the end of a run as PASS (all its tests ran and passed),
FAIL (any failed or errored), INCOMPLETE (only some ran, e.g. a selected subset) or NOT RUN, and fails
a full run (no selection) unless every case is PASS. tests/test_acceptance.py checks that every name
here exists and that the cases match the plan in 005.

SUPPORTING is evidence the S1-T8 bead also requires that is not a numbered case: the runtime role
contract (ADR-14) and the test-only reset (D-21). It is reported the same way and gated the same way.
"""

CASES = {
    "TEST-S1-01": [
        "test_intake::test_s1_01_valid_submission_records_everything_once",
        "test_intake::test_s1_01_challenge_lifetime_comes_from_the_setting",
        "test_intake::test_s1_01_the_received_page_carries_no_reference",
        "test_intake::test_s1_01_the_service_runs_as_the_application_role",
    ],
    "TEST-S1-02": [
        "test_intake::test_s1_02_invalid_fields_show_form_errors_and_record_nothing",
        "test_intake::test_s1_02_too_many_fields_is_a_400_and_records_nothing",
        "test_intake::test_s1_02_an_oversized_body_is_a_400_and_records_nothing",
        "test_intake::test_s1_02_an_address_that_normalizes_past_the_column_is_a_form_error",
        "test_intake::test_s1_02_a_file_part_is_a_400_and_records_nothing",
        "test_intake::test_s1_02_a_missing_csrf_token_is_a_403_and_records_nothing",
    ],
    "TEST-S1-03": [
        "test_intake::test_email_key",
        "test_intake::test_email_key_refuses_non_addresses",
        "test_intake::test_s1_03_variants_of_one_key_attach_to_one_application_and_reuse_the_challenge",
        "test_intake::test_s1_03_a_plus_addressed_variant_is_a_different_applicant",
        "test_intake::test_s1_03_a_repeat_after_a_failed_send_supersedes_the_challenge",
        "test_intake::test_s1_03_the_challenge_is_reused_only_while_its_send_is_queued_running_or_done",
        "test_intake::test_s1_03_a_challenge_without_any_send_is_reissued",
        "test_intake::test_s1_03_expiry_is_judged_by_the_database_clock",
        "test_intake::test_s1_03_a_repeat_after_the_challenge_expired_supersedes_it",
        "test_intake::test_s1_03_a_repeat_after_verification_is_unverified_and_goes_to_staff",
        "test_intake::test_s1_03_every_outcome_looks_identical_to_the_applicant",
    ],
    "TEST-S1-04": [
        "test_intake::test_s1_04_two_concurrent_first_submissions_make_one_application",
        "test_intake::test_s1_04_any_other_integrity_error_is_not_swallowed",
        "test_intake::test_s1_04_two_concurrent_repeats_on_an_existing_application_reuse_its_challenge",
        "test_intake::test_s1_04_two_concurrent_repeats_needing_a_new_challenge_create_only_one",
        "test_intake::test_s1_04_smoke_loop_of_concurrent_pairs",
    ],
    "TEST-S1-05": [
        "test_intake::test_s1_05_a_database_failure_commits_nothing_and_shows_try_again[after-application]",
        "test_intake::test_s1_05_a_database_failure_commits_nothing_and_shows_try_again[after-action]",
        "test_intake::test_s1_05_a_database_failure_commits_nothing_and_shows_try_again[connection-lost]",
        "test_intake::test_s1_05_a_database_failure_commits_nothing_and_shows_try_again",
        "test_intake::test_s1_05_simulated_lost_commit_acknowledgment_leaves_the_outcome_unknown_and_a_resubmission_is_safe",
        "test_confirmation::test_s1_05_a_failure_during_confirmation_records_nothing[after-verification-write]",
        "test_confirmation::test_s1_05_a_failure_during_confirmation_records_nothing",
    ],
    "TEST-S1-06": [
        "test_worker::test_s1_06_the_worker_sends_the_queued_verification_and_records_the_outcome",
        "test_worker::test_s1_06_an_action_is_invisible_to_the_worker_until_its_intake_commits",
        "test_worker::test_intake_to_file_sink_through_a_real_worker_process",
        "test_worker::test_the_link_comes_from_the_setting_and_differs_per_key",
        "test_worker::test_old_queued_work_left_behind_when_intake_replaced_the_challenge_sends_nothing",
        "test_worker::test_ineligible_challenges_end_cancelled_without_sending",
        "test_worker::test_mismatched_references_fail_closed_visibly_and_send_nothing",
    ],
    "TEST-S1-07": [
        "test_worker::test_s1_07a_claimed_then_stopped_before_sending_sends_exactly_once",
        "test_worker::test_s1_07b_sink_accepted_then_stopped_before_recording_redelivers_the_identical_link",
        "test_worker::test_s1_07c_a_killed_worker_is_recovered_automatically_by_the_running_worker_loop",
        "test_worker::test_a_recording_failure_after_the_sink_accepted_is_left_for_lease_recovery",
        "test_worker::test_the_worker_reconnects_after_its_database_connection_is_lost",
    ],
    "TEST-S1-08": [
        "test_confirmation::test_s1_08_opening_the_link_shows_the_answers_and_changes_nothing",
        "test_confirmation::test_s1_08_confirming_records_contact_control_once",
        "test_confirmation::test_s1_08_end_to_end_from_intake_through_the_worker_to_confirmation",
        "test_confirmation::test_s1_08_a_send_still_queued_when_the_link_is_used_is_cancelled_by_the_worker",
        "test_confirmation::test_s1_08_responses_built_outside_the_view_are_private_too",
        "test_confirmation::test_the_confirm_route_is_the_path_the_link_names",
    ],
    "TEST-S1-09": [
        "test_confirmation::test_s1_08_confirming_records_contact_control_once",  # the already-used token
        "test_confirmation::test_s1_09_a_tampered_or_forged_token_is_refused",
        "test_confirmation::test_s1_09_a_token_signed_with_a_retired_key_past_its_fallback_is_refused",
        "test_confirmation::test_s1_09_an_expired_challenge_is_refused_by_the_database_clock",
        "test_confirmation::test_s1_09_expiry_follows_the_database_clock_not_the_application_clock",
        "test_confirmation::test_s1_09_a_superseded_challenge_is_refused_and_the_new_one_works",
        "test_confirmation::test_s1_09_a_closed_application_cannot_be_confirmed",
        "test_confirmation::test_s1_09_a_post_naming_another_application_s_version_or_no_version_is_refused",
    ],
    "TEST-S1-10": [
        "test_confirmation::test_s1_10_two_concurrent_confirmations_of_one_link_record_it_once",
        "test_confirmation::test_s1_10_a_confirmation_racing_a_repeat_submission[confirmation]",
        "test_confirmation::test_s1_10_a_confirmation_racing_a_repeat_submission[repeat]",
    ],
    "TEST-S1-11": [
        "test_staff::test_s1_11_anonymous_visitors_are_sent_to_login_and_see_no_data",
        "test_staff::test_s1_11_real_login_and_logout_work_with_the_application_role_grants",
        "test_staff::test_s1_11_a_wrong_password_and_a_non_staff_account_cannot_log_in",
        "test_acceptance::test_s1_11_an_established_non_staff_session_reaches_no_staff_page",
        "test_staff::test_s1_11_staff_outside_the_group_are_refused_every_record",
        "test_staff::test_s1_11_every_write_path_is_refused_and_changes_nothing[read-only-staff]",
        "test_staff::test_s1_11_every_write_path_is_refused_and_changes_nothing[django-superuser]",
        "test_staff::test_every_registered_admin_is_read_only_and_the_registry_is_exactly_the_slice_views",
        "test_staff::test_changelist_query_strings_accept_only_the_declared_filters",
    ],
    "TEST-S1-12": [
        "test_staff::test_s1_12_the_group_holds_exactly_the_view_permissions_on_slice_models",
        "test_staff::test_s1_12_staff_follow_one_applicant_from_intake_to_confirmed_contact",
        "test_staff::test_s1_12_a_staff_attention_item_is_listed_and_set_apart_from_completed_steps",
        "test_staff::test_s1_12_the_list_flag_and_the_dossier_follow_one_attention_rule",
        "test_staff::test_s1_12_an_expired_challenge_is_shown_as_expired_in_its_row",
        "test_staff::test_no_staff_page_shows_a_token_link_key_or_secret",
    ],
    "TEST-S1-13": [
        "test_startup::test_check_passes_with_the_test_configuration",
        "test_startup::test_non_postgresql_engine_refuses_to_start[manage-check]",
        "test_startup::test_non_postgresql_engine_refuses_to_start[wsgi-import]",
        "test_worker::test_the_worker_command_refuses_to_start_on_a_guard[non-postgresql]",
        "test_guards::test_postgresql_is_accepted",
        "test_guards::test_missing_default_database_is_reported",
        "test_guards::test_every_non_postgresql_alias_is_reported",
        "test_database::test_connection_is_postgresql_16_15",
        "test_database::test_no_sqlite_database_is_configured_anywhere",
    ],
    "TEST-S1-14": [
        "test_startup::test_provider_credential_variable_refuses_to_start",
        "test_startup::test_smtp_backend_refuses_to_start",
        "test_worker::test_the_worker_command_refuses_to_start_on_a_guard[smtp-backend]",
        "test_worker::test_the_worker_command_refuses_to_start_on_a_guard[provider-credential]",
        "test_startup::test_production_environment_refuses_to_start",
        "test_startup::test_configured_default_mail_backend_is_a_local_sink",
        "test_guards::test_sink_backends_pass_and_smtp_is_refused",
        "test_guards::test_provider_variables_are_reported_by_name_not_value",
        "test_guards::test_each_listed_credential_name_is_refused_without_its_value",
        "test_guards::test_the_refused_name_list_is_exactly_the_documented_one",
        "test_network_guard::test_connection_to_an_external_address_is_blocked",
        "test_network_guard::test_an_smtp_send_cannot_leave_the_test_process",
        "test_network_guard::test_connect_ex_to_an_external_address_is_blocked",
        "test_acceptance::test_s1_14_ci_receives_no_provider_secret",
    ],
    "TEST-S1-15": [
        "test_acceptance::test_s1_15_the_whole_flow_writes_exactly_the_expected_history",
        "test_acceptance::test_s1_15_no_one_can_change_or_delete_versions_or_events_through_the_admin[read-only-staff]",
        "test_acceptance::test_s1_15_no_one_can_change_or_delete_versions_or_events_through_the_admin[django-superuser]",
        "test_db_roles::test_application_role_cannot_change_submission_versions",
        "test_db_roles::test_application_role_cannot_change_history_events",
    ],
    "TEST-S1-16": [
        "test_acceptance::test_s1_16_no_log_record_across_the_whole_flow_carries_a_token_address_or_name",
        "test_confirmation::test_s1_16_confirmation_logs_carry_no_token_address_or_name",
        "test_confirmation::test_redaction_rewrites_only_the_token",
    ],
    "TEST-S1-17": [
        "test_worker::test_s1_17_a_stale_worker_cannot_record_an_authoritative_result",
        "test_worker::test_s1_17_a_stale_result_cannot_overwrite_a_reclaimed_running_action",
    ],
    "TEST-S1-18": [
        "test_worker::test_s1_18_a_send_that_always_fails_reaches_failed_at_the_maximum",
        "test_worker::test_s1_18_a_failed_attempt_is_retried_only_after_the_backoff",
        "test_worker::test_s1_18_a_worker_that_dies_on_every_attempt_is_stopped_by_the_poison_rule",
        "test_acceptance::test_s1_18_a_handler_that_crashes_the_worker_on_every_attempt_is_stopped_by_the_poison_rule",
        "test_worker::test_s1_18_a_handler_defect_is_bounded_and_recorded",
        "test_worker::test_retry_backoff_doubles_per_attempt_and_is_capped",
    ],
    "TEST-S1-19": [
        "test_worker::test_s1_19_held_paused_completed_and_unknown_work_is_never_claimed",
        "test_worker::test_s1_19_a_pause_found_at_the_check_returns_the_action_without_sending",
        "test_worker::test_s1_19_two_workers_competing_for_one_action_claim_it_once",
        "test_worker::test_s1_19_two_worker_loops_process_each_action_exactly_once",
    ],
    "TEST-S1-20": [
        "test_acceptance::test_s1_20_every_named_constraint_exists_in_the_database",
        "test_acceptance::test_s1_20_no_workflow_row_points_at_a_missing_subject_or_input",
        "test_database::test_models_and_migrations_are_in_sync",
        "test_data_model::test_one_open_application_per_email_key_but_terminal_ones_do_not_count",
        "test_data_model::test_version_numbers_are_unique_per_application_and_positive",
        "test_data_model::test_at_most_one_active_challenge_per_application",
        "test_data_model::test_one_adoption_per_version_and_per_application",
        "test_data_model::test_an_adoption_cannot_use_another_applications_version_or_challenge",
        "test_data_model::test_pending_action_idempotency_key_is_unique",
        "test_data_model::test_pending_action_attempts_are_bounded_and_statuses_restricted",
        "test_data_model::test_running_requires_a_lease",
        "test_data_model::test_workflow_models_have_no_foreign_key_to_domain_models",
        "test_data_model::test_outbound_message_is_unique_per_action_attempt",
    ],
    "TEST-S1-21": [
        "test_db_roles::test_application_role_cannot_change_submission_versions",
        "test_db_roles::test_application_role_cannot_change_history_events",
        "test_db_roles::test_the_trigger_refuses_even_the_migration_owner",
        "test_db_roles::test_the_trigger_refuses_truncate_even_for_the_migration_owner",
        "test_db_roles::test_application_role_cannot_disable_triggers_or_grant_itself_privileges",
        "test_db_roles::test_application_role_cannot_switch_off_triggers_for_its_session",
        "test_db_roles::test_application_role_cannot_change_an_adoption",
        "test_db_roles::test_no_ordinary_role_can_truncate_or_delete_adoptions",
        "test_db_roles::test_the_trigger_refuses_adoption_changes_even_for_the_migration_owner",
        "test_db_roles::test_the_orm_cannot_rewrite_or_remove_an_adoption",
        "test_db_roles::test_stated_limitation_the_owner_can_disable_the_trigger",
    ],
    "TEST-S1-22": [
        "test_confirmation::test_s1_22_only_the_version_shown_and_named_is_adopted",
        "test_confirmation::test_s1_22_a_version_arriving_between_get_and_post_stays_unverified_and_goes_to_staff",
    ],
}

SUPPORTING = {
    "ADR-14 runtime role contract": [
        "test_db_roles::test_a_superuser_connection_is_refused",
        "test_db_roles::test_a_web_process_connecting_as_the_owner_is_refused",
        "test_db_roles::test_a_worker_process_connecting_as_the_retention_role_is_refused",
        "test_db_roles::test_the_web_process_refuses_a_privileged_connection",
        "test_db_roles::test_a_stale_management_value_does_not_exempt_the_web_process",
        "test_db_roles::test_this_test_process_runs_as_the_application_role",
        "test_worker::test_a_worker_process_refuses_a_privileged_login",
        "test_staff::test_the_application_role_cannot_elevate_staff_or_write_the_admin_log",
    ],
    "GATE-S1 enforcement": [
        "test_acceptance::test_the_gate_fails_a_full_run_with_a_case_not_pass_and_spares_a_selected_subset",
        "test_acceptance::test_ci_runs_the_whole_suite_with_no_selection",
        "test_acceptance::test_the_acceptance_map_names_exactly_the_cases_in_005",
        "test_acceptance::test_every_mapped_test_exists",
    ],
    "D-21 test-only privileged reset": [
        "test_db_roles::test_a_committed_write_is_removed_by_an_explicit_reset",
        "test_db_roles::test_protection_holds_after_a_reset",
        "test_db_roles::test_a_reset_against_the_wrong_identity_fails_the_run",
    ],
}


def key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name' (the function: every instance)."""
    return instance_key(nodeid).split("[", 1)[0]


def instance_key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name[param]' (one instance)."""
    path, _, name = nodeid.partition("::")
    return f"{path.rsplit('/', 1)[-1].removesuffix('.py')}::{name}"
