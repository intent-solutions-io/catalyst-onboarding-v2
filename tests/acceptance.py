"""The first-slice acceptance plan (005 S1.7, GATE-S1), the P2 correspondence plan (016 section 7, GATE-P2), the
P3 evidence and assessment plan (018 section 9, GATE-P3), the P4 agreements plan (021 section 12, GATE-P4) and the
P5 provisioning plan (023 section 9, GATE-P5) and the P6
staging plan (026 section 11, GATE-STAGING), each mapped to the tests that prove each case (S1-T8; P2 task 2C; P3
task 3C; P4 task 4C; P5 task 5C; P6 task 6C).

Each case names test functions as "module::function", where every parametrized instance counts, or
one instance as "module::function[id]" where a case depends on that instance specifically. tests/conftest.py reports every case at the end of a run as PASS (all its tests ran and passed),
FAIL (any failed or errored), INCOMPLETE (only some ran, e.g. a selected subset) or NOT RUN, and fails
a full run (no selection) unless every case is PASS. tests/test_acceptance.py checks that every name
here exists and that the cases match the plan in 005.

SUPPORTING is evidence the S1-T8 bead also requires that is not a numbered case: the runtime role
contract (ADR-14) and the test-only reset (D-21). It is reported the same way and gated the same way.
"""

import re

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


# P2 acceptance plan (016 section 7; GATE-P2): each case names the tests that prove it, by the case numbers
# in their names (a test may prove several cases). Reported and gated like the S1 cases (016 2C).
P2_CASES = {
    "TEST-P2-01": [
        "test_inbound::test_p2_01_a_trusted_reply_is_correlated_and_makes_its_question_reply_pending",
    ],
    "TEST-P2-02": [
        "test_processing::test_p2_10_02_a_single_autoresponder_is_classified_never_answered_and_neither_suppresses_nor_pauses",
        "test_processing::test_p2_34_02_the_loop_threshold_pauses_automation_and_opens_a_staff_item",
    ],
    "TEST-P2-03": [
        "test_outbound::test_p2_03_25_admissible_evidence_resolves_the_message_and_the_attempt_stays_unknown",
    ],
    "TEST-P2-04": [
        "test_reminders::test_e1_a_released_reminder_waits_at_least_the_grace",
        "test_reminders::test_e2_a_frozen_reminder_send_follows_its_question",
        "test_reminders::test_p2_04_a_pending_reply_holds_the_reminder_and_staff_outcomes_release_or_cancel_it",
        "test_reminders::test_p2_04_a_reminder_claimed_while_a_reply_is_pending_is_held_by_the_handler",
        "test_reminders::test_reminder_race_a_frozen_send_past_its_check_completes_once_and_later_reminders_respect_the_reply",
        "test_reminders::test_reminder_race_a_reply_committed_before_the_frozen_send_check_holds_the_mail",
        "test_reminders::test_reminder_race_the_reminder_check_commits_first_and_its_frozen_send_then_respects_the_reply",
        "test_reminders::test_reminder_race_the_reply_commits_before_the_reminder_check_so_no_reminder",
    ],
    "TEST-P2-05": [
        "test_outbound::test_p2_05_a_paused_application_sends_nothing_until_resumed",
        "test_reminders::test_p2_05_a_pause_stops_every_automated_kind_and_resume_spreads_reminders_without_a_burst",
        "test_reminders::test_reconciliation_is_not_held_by_a_pause",
        "test_worker::test_s1_19_held_paused_completed_and_unknown_work_is_never_claimed",
    ],
    "TEST-P2-06": [
        "test_processing::test_c4_staff_association_records_prior_values_and_an_event",
        "test_processing::test_p2_06_53_an_unmatched_message_is_resolved_without_ssh_and_leaves_a_record_without_an_application",
        "test_reminders::test_resolving_an_escalation_needs_resolve_exception",
        "test_staff_screens::test_operator_journey_through_the_normal_screens",
    ],
    "TEST-P2-07": [
        "test_inbound::test_p2_07_46_a_uidvalidity_change_resyncs_with_no_new_effect_even_mid_batch",
    ],
    "TEST-P2-08": [
        "test_processing::test_d3_d4_staff_decide_only_a_persons_trusted_reply_and_need_every_outcome",
        "test_processing::test_p2_08_09_staff_confirm_each_outcome_and_a_reply_never_satisfies_by_itself",
        "test_reminders::test_p2_08_two_questions_in_separate_messages_a_partial_then_full_answer_touches_only_the_first",
    ],
    "TEST-P2-09": [
        "test_processing::test_d3_d4_staff_decide_only_a_persons_trusted_reply_and_need_every_outcome",
        "test_processing::test_p2_08_09_staff_confirm_each_outcome_and_a_reply_never_satisfies_by_itself",
    ],
    "TEST-P2-10": [
        "test_processing::test_p2_10_02_a_single_autoresponder_is_classified_never_answered_and_neither_suppresses_nor_pauses",
    ],
    "TEST-P2-11": [
        "test_reminders::test_p2_11_a_confirmed_staff_message_is_sent_while_paused_and_nothing_automated_runs",
    ],
    "TEST-P2-12": [
        "test_inbound::test_4_1_a_regressed_cursor_becomes_a_recovery_and_skips_nothing",
        "test_inbound::test_p2_12_the_same_bytes_seen_again_and_our_own_filed_copy_have_no_new_effect",
        "test_outbound::test_p2_12_approving_a_question_twice_freezes_and_queues_one_message",
        "test_outbound::test_p2_12_two_concurrent_approvals_freeze_one_message",
    ],
    "TEST-P2-13": [
        "test_inbound::test_p2_13_the_same_message_id_with_different_bytes_is_kept_with_a_staff_item",
    ],
    "TEST-P2-14": [
        "test_inbound::test_p2_14_malformed_mime_is_recorded_and_the_cursor_passes_it",
    ],
    "TEST-P2-15": [
        "test_inbound::test_p2_15_an_oversize_message_is_recorded_from_its_headers_only",
        "test_inbound::test_p2_15_an_oversize_message_never_causes_a_full_body_fetch",
    ],
    "TEST-P2-16": [
        "test_inbound::test_p2_16_17_the_trust_table_decides_every_effect",
    ],
    "TEST-P2-17": [
        "test_inbound::test_p2_16_17_the_trust_table_decides_every_effect",
    ],
    "TEST-P2-18": [
        "test_inbound::test_p2_18_a_bounce_is_matched_only_through_its_embedded_message_id",
        "test_inbound::test_p2_18_a_reply_to_a_closed_application_is_never_applied_to_a_newer_one",
        "test_inbound::test_p2_18_unmatched_mail_and_a_reply_to_a_closed_application_go_to_staff",
    ],
    "TEST-P2-19": [
        "test_inbound::test_p2_19_a_collector_killed_mid_message_loses_nothing_and_duplicates_nothing",
    ],
    "TEST-P2-20": [
        "test_inbound::test_4_1_a_regressed_cursor_becomes_a_recovery_and_skips_nothing",
        "test_inbound::test_b5_an_unestablished_message_is_matched_by_metadata_after_a_resync",
        "test_inbound::test_p2_20_a_lost_or_regressed_cursor_recovers_without_skipping_or_duplicating",
    ],
    "TEST-P2-21": [
        "test_inbound::test_p2_21_a_lease_lost_between_messages_rolls_that_message_back_and_stops_the_pass",
    ],
    "TEST-P2-22": [
        "test_inbound::test_p2_22_one_claim_per_pass_one_successor_and_the_chain_survives_a_final_failure",
        "test_inbound::test_p2_23_an_authentication_failure_blocks_without_a_retry_chain_and_only_restart_resumes",
    ],
    "TEST-P2-23": [
        "test_inbound::test_p2_23_an_authentication_failure_blocks_without_a_retry_chain_and_only_restart_resumes",
        "test_inbound::test_p2_23_an_unreachable_server_backs_off_then_blocks_at_the_bound",
        "test_inbound::test_p2_23_collected_content_never_reaches_logs_items_events_or_actions",
    ],
    "TEST-P2-24": [
        "test_inbound::test_m6_a_collector_facing_an_untrusted_certificate_blocks_without_logging_in",
        "test_inbound::test_m6_imap_verifies_the_chain_and_hostname_and_has_no_plaintext_path",
        "test_inbound::test_m6_smtp_never_falls_back_to_plaintext_when_starttls_is_refused",
        "test_inbound::test_m6_smtp_starttls_verifies_the_chain_and_the_hostname",
    ],
    "TEST-P2-25": [
        "test_inbound::test_p2_25_a_catalyst_filed_copy_in_sent_is_never_evidence_even_if_mislabelled",
        "test_outbound::test_p2_03_25_admissible_evidence_resolves_the_message_and_the_attempt_stays_unknown",
        "test_outbound::test_p2_25_a_catalyst_filed_copy_is_never_evidence_whatever_its_label",
        "test_outbound::test_p2_25_inadmissible_evidence_is_ignored_and_the_outcome_stays_unknown",
    ],
    "TEST-P2-26": [
        "test_inbound::test_p2_26_an_accepted_send_files_one_copy_and_an_append_failure_never_sends_again",
        "test_outbound::test_p2_26_a_permanent_rejection_is_never_resent_unchanged_only_revised",
        "test_outbound::test_p2_26_a_resend_after_a_held_channel_cancels_the_held_action_and_counts_blocks_per_series",
        "test_outbound::test_p2_26_a_resend_is_refused_for_a_withdrawn_question_and_a_note_with_a_link_changes_nothing",
        "test_outbound::test_p2_26_a_resend_that_ends_unknown_again_gets_its_own_reconciliation_checks",
        "test_outbound::test_p2_26_abandon_records_the_operator_decision_not_a_provider_verdict",
        "test_outbound::test_p2_26_staff_decide_an_unknown_send_and_no_decision_rewrites_the_attempt",
    ],
    "TEST-P2-27": [
        "test_outbound::test_p2_27_a_crash_after_acceptance_and_before_recording_is_reconciled_never_resent",
        "test_outbound::test_p2_27_a_real_worker_killed_after_acceptance_is_recovered_without_a_second_send",
        "test_outbound::test_p2_27_a_reclaim_during_the_exchange_discards_the_stale_result_and_sends_once",
    ],
    "TEST-P2-28": [
        "test_reminders::test_e2_an_incomplete_cursor_makes_the_watermark_stale",
        "test_reminders::test_p2_28_a_reminder_waits_for_a_complete_collection_after_its_due_time",
        "test_reminders::test_reminder_race_a_frozen_send_past_its_check_completes_once_and_later_reminders_respect_the_reply",
        "test_reminders::test_reminder_race_a_reply_committed_before_the_frozen_send_check_holds_the_mail",
        "test_reminders::test_reminder_race_the_reminder_check_commits_first_and_its_frozen_send_then_respects_the_reply",
        "test_reminders::test_reminder_race_the_reply_commits_before_the_reminder_check_so_no_reminder",
    ],
    "TEST-P2-29": [
        "test_reminders::test_e2_an_unapproved_reminder_template_waits_for_staff_and_the_chain_survives",
        "test_reminders::test_e2_reminders_due_together_never_leave_in_a_burst",
        "test_reminders::test_p2_29_cadence_maximum_and_escalation_after_the_last_reminder",
        "test_reminders::test_p2_29_quiet_hours_defer_to_their_end_and_the_minimum_gap_is_kept",
        "test_reminders::test_p2_29_quiet_hours_wrap_midnight",
    ],
    "TEST-P2-30": [
        "test_reminders::test_e2_a_frozen_reminder_send_follows_its_question",
        "test_reminders::test_p2_04_a_pending_reply_holds_the_reminder_and_staff_outcomes_release_or_cancel_it",
        "test_reminders::test_p2_30_the_projection_never_revives_finished_actions_or_creates_reminders",
        "test_reminders::test_p2_50_withdrawal_effects",
    ],
    "TEST-P2-31": [
        "test_reminders::test_p2_31_a_pause_during_a_running_reminder_and_resume_across_applications",
    ],
    "TEST-P2-32": [
        "test_processing::test_p2_32_staff_confirm_while_process_reply_holds_the_lock",
        "test_processing::test_p2_32_staff_confirmation_and_process_reply_race_and_exactly_one_decides",
    ],
    "TEST-P2-33": [
        "test_processing::test_p2_33_a_bounce_for_a_message_that_is_not_ours_is_unmatched_and_a_soft_bounce_is_recorded",
        "test_processing::test_p2_33_only_a_hard_bounce_for_our_message_and_the_verified_recipient_pauses",
    ],
    "TEST-P2-34": [
        "test_processing::test_p2_34_02_the_loop_threshold_pauses_automation_and_opens_a_staff_item",
        "test_processing::test_p2_34_loop_threshold_boundary_and_recount_after_staff_resolve",
    ],
    "TEST-P2-35": [
        "test_reminders::test_p2_35_a_late_reply_to_a_satisfied_question_changes_nothing",
        "test_reminders::test_p2_50_withdrawal_effects",
    ],
    "TEST-P2-36": [
        "test_outbound::test_p2_36_the_recipient_is_always_the_frozen_verified_address",
        "test_reminders::test_p2_54_36_a_staff_message_and_a_reply_to_address_change_no_identity_and_no_recipient",
    ],
    "TEST-P2-37": [
        "test_outbound::test_p2_37_only_owner_approved_versions_render_and_approved_text_is_fixed",
    ],
    "TEST-P2-38": [
        "test_outbound::test_p2_38_a_recipient_with_a_line_break_cannot_be_framed",
        "test_outbound::test_p2_38_no_input_can_add_a_header",
    ],
    "TEST-P2-39": [
        "test_inbound::test_p2_39_47_no_table_stores_original_message_bytes",
        "test_inbound::test_p2_39_inbound_records_cannot_be_rewritten_or_removed_by_the_application_role",
        "test_outbound::test_p2_39_the_application_role_cannot_rewrite_or_remove_outbound_records",
        "test_outbound::test_p2_39_the_application_role_updates_only_the_status_columns",
        "test_outbound::test_p2_39_the_p2_groups_hold_exactly_the_matrix_permissions",
    ],
    "TEST-P2-40": [
        "test_guards::test_each_listed_credential_name_is_refused_without_its_value",
        "test_guards::test_provider_variables_are_reported_by_name_not_value",
        "test_inbound::test_p2_40_the_imap_peer_is_checked_before_login",
        "test_network_guard::test_connection_to_an_external_address_is_blocked",
        "test_outbound::test_p2_40_a_non_loopback_mail_host_refuses_to_start",
        "test_outbound::test_p2_40_an_evidence_source_is_refused_outside_test",
        "test_outbound::test_p2_40_only_loopback_or_the_named_test_host_may_be_configured",
        "test_outbound::test_p2_40_the_connected_peer_is_checked_before_any_credential",
    ],
    "TEST-P2-41": [
        "test_inbound::test_p2_41_g1_reports_a_healthy_collector_and_a_broken_chain",
        "test_inbound::test_p2_41_g1_reports_a_stale_watermark",
        "test_outbound::test_p2_41_g3_clears_once_staff_have_decided",
        "test_outbound::test_p2_41_g3_reports_the_send_anomalies",
        "test_processing::test_g2_g6_every_reply_signal_reports_its_seeded_anomaly",
        "test_processing::test_g2_g6_reply_health",
        "test_reminders::test_g4_g5_g6_reminder_health_reports_each_seeded_anomaly",
        "test_reminders::test_g4_ignores_closed_applications_and_a_reminder_still_in_flight",
        "test_reminders::test_g7_mail_behaviour_health",
        "test_reminders::test_health_command_exit_codes",
    ],
    "TEST-P2-42": [
        "test_staff::test_every_registered_admin_is_read_only_and_the_registry_is_exactly_the_slice_views",
        "test_staff_screens::test_operator_journey_through_the_normal_screens",
        "test_staff_screens::test_p2_42_52_each_remaining_screen_action_needs_its_own_permission",
        "test_staff_screens::test_p2_42_a_malformed_target_is_refused_not_an_error",
        "test_staff_screens::test_p2_42_a_refused_preview_keeps_the_typed_text_escaped",
        "test_staff_screens::test_p2_42_a_role_reads_only_the_pages_its_work_needs",
        "test_staff_screens::test_p2_42_a_service_refusal_reaches_staff_as_a_code",
        "test_staff_screens::test_p2_42_actions_are_post_only_csrf_protected_and_one_object_each",
        "test_staff_screens::test_p2_42_applications_can_be_found_without_an_open_item",
        "test_staff_screens::test_p2_42_each_application_action_needs_its_permission",
        "test_staff_screens::test_p2_42_identity_resolution_needs_the_decision_maker_through_the_screen",
        "test_staff_screens::test_p2_42_pages_need_an_active_staff_account_with_a_correspondence_permission",
        "test_staff_screens::test_p2_42_pause_resume_withdraw_and_approve_through_the_screens",
        "test_staff_screens::test_p2_42_reply_confirmation_shows_the_derivative_escaped_and_checks_its_digest",
        "test_staff_screens::test_p2_42_staff_message_preview_and_confirmation_through_the_screens",
        "test_staff_screens::test_p2_42_template_approval_needs_the_owner_role",
        "test_staff_screens::test_p2_42_template_approval_through_the_screen_approves_exactly_what_was_shown",
        "test_staff_screens::test_p2_42_the_admin_stays_read_only_and_templates_never_mark_text_safe",
        "test_staff_screens::test_p2_42_the_item_page_shows_the_evidence_and_offers_only_lawful_decisions",
        "test_staff_screens::test_p2_42_the_queue_and_item_pages_escape_hostile_application_names",
        "test_staff_screens::test_the_dossier_links_to_the_correspondence_screen_only_for_a_user_who_could_open_it",
    ],
    "TEST-P2-43": [
        "test_processing::test_p2_43_a_persons_reply_holds_interpretation_for_p3_and_asks_staff",
        "test_processing::test_p2_43_correspondence_imports_no_model_client",
        "test_processing::test_p2_43_no_network_outside_the_transports_and_no_interpret_handler",
        "test_processing::test_p3_eligibility_refuses_degraded_or_untrusted_text",
        "test_processing::test_p3_interface_validation_rules",
        "test_processing::test_p3_validation_is_total_and_refuses_straddling_long_or_stale_spans",
    ],
    "TEST-P2-44": [
        "test_inbound::test_p2_44_derivation_golden_case_for_the_current_derivation_version",
        "test_processing::test_p2_44_quote_stripping_golden_cases",
        "test_processing::test_p2_44_quote_stripping_keeps_from_lines_and_catches_wrapped_attributions",
    ],
    "TEST-P2-45": [
        "test_outbound::test_p2_40_the_connected_peer_is_checked_before_any_credential",
        "test_reminders::test_p2_45_a_confirmed_staff_message_to_a_non_test_host_is_refused_before_any_connection",
        "test_reminders::test_p2_45_a_staff_message_cannot_reach_a_non_test_host",
        "test_reminders::test_p2_45_confirmation_refuses_any_change_since_the_preview",
        "test_reminders::test_p2_45_content_checks_refuse_links_credentials_and_controls",
    ],
    "TEST-P2-46": [
        "test_inbound::test_p2_07_46_a_uidvalidity_change_resyncs_with_no_new_effect_even_mid_batch",
        "test_inbound::test_p2_46_a_crash_during_resync_recovers_with_no_new_effect",
    ],
    "TEST-P2-47": [
        "test_inbound::test_p2_39_47_no_table_stores_original_message_bytes",
        "test_inbound::test_p2_47_a_redaction_version_bump_rederives_from_the_mailbox_and_keeps_no_old_text",
        "test_inbound::test_p2_47_a_wrapped_link_is_redacted_without_swallowing_the_following_words",
        "test_inbound::test_p2_47_confirmation_links_are_redacted_in_every_encoding_and_the_text_is_a_labelled_derivative",
        "test_inbound::test_p2_47_rederivation_without_the_source_rederives_the_stored_derivative",
    ],
    "TEST-P2-48": [
        "test_outbound::test_p2_48_a_failure_known_before_the_marker_write_is_retried_within_its_bound",
        "test_outbound::test_p2_48_a_real_disconnect_after_354_is_never_accepted_or_retried_blindly",
        "test_outbound::test_p2_48_a_refused_connection_is_a_channel_fault",
        "test_outbound::test_p2_48_a_write_failure_once_the_marker_write_started_is_unknown_and_never_resent",
        "test_outbound::test_p2_48_an_authentication_refusal_is_a_channel_fault",
        "test_outbound::test_p2_48_each_protocol_phase_maps_to_its_outcome_class",
        "test_outbound::test_p2_48_events_logs_errors_and_items_carry_no_address_subject_body_or_credential",
        "test_outbound::test_p2_48_starttls_is_required_unless_the_host_is_loopback_with_tls_off",
        "test_outbound::test_p2_a7_an_uncertain_send_without_an_unknown_attempt_reaches_staff",
        "test_outbound::test_p2_a7_evidence_after_the_poison_rule_resolves_its_item",
        "test_outbound::test_p2_a7_the_poison_rule_ends_a_send_unknown_with_a_staff_item",
    ],
    "TEST-P2-49": [
        "test_outbound::test_p2_26_a_permanent_rejection_is_never_resent_unchanged_only_revised",
        "test_outbound::test_p2_49_a_restarted_worker_sends_exactly_the_frozen_message",
    ],
    "TEST-P2-50": [
        "test_reminders::test_p2_50_a_satisfied_question_is_not_withdrawn",
        "test_reminders::test_p2_50_withdrawal_cancels_held_reminders_and_the_escalation",
        "test_reminders::test_p2_50_withdrawal_effects",
    ],
    "TEST-P2-51": [
        "test_inbound::test_p2_20_a_lost_or_regressed_cursor_recovers_without_skipping_or_duplicating",
        "test_inbound::test_p2_51_bootstrap_records_its_start_mode_and_refuses_a_collected_mailbox",
    ],
    "TEST-P2-52": [
        "test_outbound::test_p2_39_the_p2_groups_hold_exactly_the_matrix_permissions",
        "test_outbound::test_p2_52_each_2b1_service_needs_its_role",
        "test_processing::test_d3_d4_staff_decide_only_a_persons_trusted_reply_and_need_every_outcome",
        "test_processing::test_f_identity_resolutions_are_refused_to_operators",
        "test_processing::test_f_reply_and_send_items_are_not_resolvable_through_resolve_exception",
        "test_processing::test_p2_52_each_2b3_service_needs_its_role",
        "test_reminders::test_p2_52_each_2b4_service_needs_its_permission_and_a_superuser_is_refused",
        "test_staff_screens::test_p2_42_52_each_remaining_screen_action_needs_its_own_permission",
        "test_staff_screens::test_p2_52_operator_actions_need_the_matching_permission_through_the_screens",
        "test_staff_screens::test_p2_52_restart_needs_the_decision_maker_through_the_screen",
    ],
    "TEST-P2-53": [
        "test_processing::test_p2_06_53_an_unmatched_message_is_resolved_without_ssh_and_leaves_a_record_without_an_application",
    ],
    "TEST-P2-54": [
        "test_processing::test_c4_association_refuses_a_closed_target_or_an_automatic_message",
        "test_processing::test_c4_staff_association_records_prior_values_and_an_event",
        "test_processing::test_p2_54_associating_an_unverified_reply_needs_the_decision_maker_and_changes_no_identity",
        "test_reminders::test_p2_54_36_a_staff_message_and_a_reply_to_address_change_no_identity_and_no_recipient",
    ],
}



# P3 acceptance plan (018 section 9; GATE-P3, task 3C): each case names the tests that prove it, by the case
# numbers in their names plus the review tests that prove the same case. Reported and gated like S1 and P2.
# GATE-P3 proves software, permissions, provenance and workflow; it is not a validation of selection quality
# (011 section 11, 018 section 15).
P3_CASES = {
    "TEST-P3-01": [
        "test_assessment::test_p3_01_a_valid_output_is_stored_with_provenance_and_the_stage_moves_for_staff",
    ],
    "TEST-P3-02": [
        "test_assessment::test_p3_02_25_malformed_output_gets_one_repair_then_staff_and_never_a_third_request",
        "test_assessment::test_p3_02_27_provider_errors_are_bounded_then_staff_with_no_stage_change",
        "test_assessment::test_p3_02_no_model_outside_the_test_mode_refuses_before_any_reservation",
    ],
    "TEST-P3-03": [
        "test_assessment::test_p3_03_24_injected_text_stays_data_and_an_obeying_model_changes_nothing",
    ],
    "TEST-P3-04": [
        "test_decision::test_p3_04_no_decision_authority_refuses_everyone_including_superusers",
    ],
    "TEST-P3-05": [
        "test_evidence::test_p3_05_15_unsafe_urls_are_refused",
        "test_evidence::test_p3_05_a_host_outside_the_settings_allow_list_is_refused_and_nothing_is_stored",
        "test_evidence::test_p3_05_fetch_itself_refuses_a_host_off_the_settings_list_and_fixtures_outside_test",
        "test_evidence::test_p3_05_the_path_prefix_is_a_path_segment_prefix",
    ],
    "TEST-P3-06": [
        "test_evidence::test_p3_06_18_a_transient_failure_retries_then_is_unavailable_never_a_negative_finding",
    ],
    "TEST-P3-07": [
        "test_clarification::test_p3_07_42_a_confirmed_answer_starts_one_reassessment_on_a_new_snapshot_with_the_answer",
    ],
    "TEST-P3-08": [
        "test_assessment::test_p3_08_a_newer_unadopted_version_never_enters_the_snapshot",
        "test_assessment::test_p3_08_21_the_snapshot_names_the_adopted_version_and_only_its_own_captures",
    ],
    "TEST-P3-09": [
        "test_evidence::test_p3_09_activation_releases_only_eligible_held_rows_with_events",
    ],
    "TEST-P3-10": [
        "test_evidence::test_p3_10_slots_per_claim_and_source_and_a_changed_adoption_is_refused",
    ],
    "TEST-P3-11": [
        "test_evidence::test_p3_11_address_classification",
    ],
    "TEST-P3-12": [
        "test_evidence::test_p3_12_mixed_dns_answers_refuse_and_a_peer_mismatch_sends_nothing",
    ],
    "TEST-P3-13": [
        "test_evidence::test_p3_13_redirect_hosts_are_bounded_by_the_settings_list",
        "test_evidence::test_p3_13_redirects_are_revalidated",
    ],
    "TEST-P3-14": [
        "test_evidence::test_p3_14_the_byte_cap_truncates_and_the_deadline_stops_a_slow_drip",
        "test_evidence::test_p3_14_the_deadline_bounds_a_server_that_drips_its_headers",
        "test_evidence::test_p3_14_the_deadline_bounds_a_server_that_never_finishes_the_tls_handshake",
    ],
    "TEST-P3-15": [
        "test_evidence::test_p3_05_15_unsafe_urls_are_refused",
        "test_evidence::test_p3_15_a_malformed_applicant_url_is_refused_and_never_leaves_the_application_stuck",
        "test_evidence::test_p3_15_a_malformed_url_claim_ends_refused_and_collection_completes",
        "test_evidence::test_p3_15_content_type_and_encoding_are_refused_and_refusals_are_not_retried",
    ],
    "TEST-P3-16": [
        "test_evidence::test_p3_16_requests_carry_no_cookie_or_credential_and_logs_hold_no_path",
    ],
    "TEST-P3-17": [
        "test_evidence::test_p3_17_captures_are_immutable_and_hold_no_raw_bytes",
    ],
    "TEST-P3-18": [
        "test_evidence::test_p3_06_18_a_transient_failure_retries_then_is_unavailable_never_a_negative_finding",
        "test_evidence::test_p3_18_private_and_missing_pages_are_never_negative_findings",
    ],
    "TEST-P3-19": [
        "test_evidence::test_p3_19_completion_happens_once_when_the_last_fetches_finish",
        "test_evidence::test_p3_19_two_last_fetches_racing_complete_collection_exactly_once",
    ],
    "TEST-P3-20": [
        "test_evidence::test_p3_20_a_required_unavailable_item_holds_for_staff_until_they_proceed_or_refetch",
        "test_evidence::test_p3_20_proceed_without_moves_on_and_resolves_the_item",
    ],
    "TEST-P3-21": [
        "test_assessment::test_p3_08_21_the_snapshot_names_the_adopted_version_and_only_its_own_captures",
    ],
    "TEST-P3-22": [
        "test_assessment::test_p3_22_a_fabricated_alias_is_repaired_once",
        "test_assessment::test_p3_22_quotes_must_carry_substance_and_never_only_placeholders",
    ],
    "TEST-P3-23": [
        "test_assessment::test_p3_23_admit_against_an_unsupported_required_criterion_is_flagged_not_changed",
    ],
    "TEST-P3-24": [
        "test_assessment::test_p3_03_24_injected_text_stays_data_and_an_obeying_model_changes_nothing",
    ],
    "TEST-P3-25": [
        "test_assessment::test_p3_02_25_malformed_output_gets_one_repair_then_staff_and_never_a_third_request",
    ],
    "TEST-P3-26": [
        "test_assessment::test_p3_26_a_race_for_the_last_unit_is_serialized_by_the_advisory_lock",
        "test_assessment::test_p3_26_global_concurrency_waits_without_spending_an_attempt",
        "test_assessment::test_p3_26_the_daily_budget_defaults_to_zero_and_stops_before_any_call",
        "test_assessment::test_p3_26_the_per_snapshot_budget_counts_every_recorded_invocation",
        "test_assessment::test_p3_26_unknown_usage_counts_at_its_full_reservation_against_the_application",
    ],
    "TEST-P3-27": [
        "test_assessment::test_p3_02_27_provider_errors_are_bounded_then_staff_with_no_stage_change",
    ],
    "TEST-P3-28": [
        "test_assessment::test_p3_28_input_changed_between_freeze_and_call_refuses_without_a_call",
    ],
    "TEST-P3-29": [
        "test_assessment::test_p3_29_57_names_contacts_links_and_identifiers_never_leave",
        "test_assessment::test_p3_29_a_claim_cannot_forge_prompt_structure",
    ],
    "TEST-P3-30": [
        "test_assessment::test_p3_30_live_models_are_refused_everywhere_and_requests_are_disabled",
    ],
    "TEST-P3-31": [
        "test_assessment::test_p3_31_56_a_crash_after_the_call_is_counted_and_yields_at_most_one_result",
        "test_assessment::test_p3_31_a_redelivered_finished_run_is_never_called_again",
        "test_assessment::test_p3_31_the_invocation_is_committed_before_the_model_is_called",
    ],
    "TEST-P3-32": [
        "test_assessment::test_p3_32_a_reasoning_part_is_never_persisted",
    ],
    "TEST-P3-33": [
        "test_assessment::test_p3_33_a_tampered_prompt_pack_is_refused_at_enqueue",
        "test_assessment::test_p3_33_finished_runs_cannot_be_rewritten_by_any_role",
    ],
    "TEST-P3-34": [
        "test_clarification::test_p3_34_a_harmful_or_linked_proposal_never_becomes_a_question",
        "test_clarification::test_p3_34_a_model_proposal_is_stored_proposed_with_its_gap_and_is_unsendable_until_approved",
        "test_clarification::test_p3_34_a_proposal_must_name_its_evidence_gap",
    ],
    "TEST-P3-35": [
        "test_clarification::test_p3_35_duplicates_are_dropped_and_a_round_holds_at_most_three",
    ],
    "TEST-P3-36": [
        "test_clarification::test_p3_36_authoring_needs_its_permission_a_known_criterion_and_a_gap",
        "test_clarification::test_p3_36_staff_author_a_question_through_the_screen_and_it_is_sent_through_p2",
    ],
    "TEST-P3-37": [
        "test_clarification::test_p3_37_39_one_reply_is_interpreted_once_as_advice_and_staff_still_confirm",
        "test_clarification::test_review_one_call_covers_every_pending_question_of_a_reply",
    ],
    "TEST-P3-38": [
        "test_clarification::test_p3_38_ineligible_replies_make_no_call",
        "test_clarification::test_p3_38_the_default_model_setting_refuses_before_any_record_of_a_call",
        "test_clarification::test_recheck_a_closed_application_is_never_interpreted",
        "test_clarification::test_review_a_paused_or_deactivated_interpretation_records_nothing",
    ],
    "TEST-P3-39": [
        "test_clarification::test_p3_37_39_one_reply_is_interpreted_once_as_advice_and_staff_still_confirm",
        "test_clarification::test_p3_39_a_quote_that_is_not_in_the_reply_gets_one_repair_then_no_proposal",
        "test_clarification::test_recheck_our_question_re_cased_and_numbered_is_still_ours",
        "test_clarification::test_review_our_own_words_repeated_unquoted_are_never_the_applicants_answer",
    ],
    "TEST-P3-40": [
        "test_clarification::test_p3_40_evidence_required_but_absent_is_reported",
        "test_clarification::test_review_the_evidence_flag_counts_only_the_applicants_own_links",
    ],
    "TEST-P3-41": [
        "test_clarification::test_p3_41_55_a_staff_decision_before_the_call_stops_the_disclosure",
        "test_clarification::test_p3_41_a_rederived_reply_ends_text_changed",
        "test_clarification::test_p3_41_a_staff_decision_during_the_call_supersedes_the_result",
        "test_clarification::test_recheck_a_question_withdrawn_during_the_call_supersedes_the_result",
        "test_clarification::test_recheck_the_reply_screen_ignores_advice_on_an_older_derivative",
    ],
    "TEST-P3-42": [
        "test_clarification::test_p3_07_42_a_confirmed_answer_starts_one_reassessment_on_a_new_snapshot_with_the_answer",
        "test_clarification::test_p3_42_rounds_are_bounded_and_the_last_round_returns_to_staff",
        "test_clarification::test_p3_42_withdrawing_the_last_open_question_ends_the_round",
        "test_clarification::test_review_the_last_round_proposes_nothing_at_default_settings",
    ],
    "TEST-P3-43": [
        "test_decision::test_p3_43_51_a_newly_confirmed_answer_makes_the_run_stale",
    ],
    "TEST-P3-44": [
        "test_decision::test_p3_44_a_decision_is_one_transaction_with_its_held_follow_on",
        "test_decision::test_review_a_decision_withdraws_unsent_questions_and_none_can_be_sent_afterwards",
        "test_decision::test_review_a_failure_creating_the_follow_on_rolls_everything_back",
    ],
    "TEST-P3-45": [
        "test_decision::test_p3_45_two_concurrent_decisions_one_wins",
    ],
    "TEST-P3-46": [
        "test_decision::test_p3_46_decisions_are_append_only_for_every_role",
        "test_decision::test_review_a_supplied_transaction_marker_is_overwritten_and_truncate_is_refused",
    ],
    "TEST-P3-47": [
        "test_decision::test_p3_47_an_identity_item_blocks_and_admit_is_refused_while_paused",
        "test_decision::test_recheck_an_open_sent_question_blocks_the_decision",
    ],
    "TEST-P3-48": [
        "test_decision::test_p3_48_the_screen_records_a_decision_through_one_post",
        "test_decision::test_p3_48_the_screen_shows_everything_escaped_and_only_permitted_outcomes",
        "test_decision::test_review_hostile_claim_text_is_escaped_and_nothing_is_preselected",
    ],
    "TEST-P3-49": [
        "test_decision::test_p3_49_a_repeat_after_decline_creates_nothing_new_and_asks_staff",
    ],
    "TEST-P3-50": [
        "test_clarification::test_review_layering_holds_and_no_assessment_code_confirms_an_outcome",
        "test_assessment::test_p3_50_no_provider_client_and_no_output_field_in_control_flow",
        "test_assessment::test_p3_50_the_recommendation_never_chooses_the_next_step",
    ],
    "TEST-P3-51": [
        "test_decision::test_p3_51_a_completed_re_fetch_after_the_screen_was_shown_is_refused",
        "test_decision::test_p3_43_51_a_newly_confirmed_answer_makes_the_run_stale",
        "test_decision::test_p3_51_a_changed_question_set_or_a_re_fetch_is_refused",
        "test_decision::test_review_exact_refusals_for_pending_evidence_a_run_in_flight_and_a_decided_stage",
    ],
    "TEST-P3-52": [
        "test_decision::test_p3_52_no_role_can_move_into_a_decided_stage_without_a_decision_row",
        "test_decision::test_review_the_backstop_needs_a_matching_decision_from_this_very_transaction",
        "test_decision::test_review_the_backstop_refuses_another_applications_decision_and_a_decided_insert",
    ],
    "TEST-P3-53": [
        "test_decision::test_p3_53_after_pol05_a_superuser_or_ungranted_staff_is_refused_and_the_setting_takes_one_rule",
        "test_decision::test_review_a_group_grant_never_confers_the_decision",
    ],
    "TEST-P3-54": [
        "test_evidence::test_p3_54_classify_has_no_environment_branch_and_fixtures_need_the_test_environment",
    ],
    "TEST-P3-55": [
        "test_clarification::test_p3_41_55_a_staff_decision_before_the_call_stops_the_disclosure",
    ],
    "TEST-P3-56": [
        "test_assessment::test_p3_31_56_a_crash_after_the_call_is_counted_and_yields_at_most_one_result",
        "test_assessment::test_p3_56_a_pause_before_the_invocation_refunds_and_records_nothing",
        "test_assessment::test_p3_56_the_poison_path_abandons_the_run_and_opens_a_staff_item",
        "test_clarification::test_review_an_interrupted_attempt_stays_counted_and_exhaustion_abandons_it",
    ],
    "TEST-P3-57": [
        "test_assessment::test_p3_29_57_names_contacts_links_and_identifiers_never_leave",
        "test_assessment::test_p3_57_names_applicant_needs_a_full_name_in_the_sent_text",
        "test_assessment::test_p3_57_names_are_scrubbed_on_word_boundaries",
        "test_assessment::test_p3_57_scrubbing_a_hostile_page_is_linear",
        "test_assessment::test_p3_57_zero_width_and_full_width_names_are_still_scrubbed",
        "test_clarification::test_review_a_confirmed_answer_leaves_as_one_scrubbed_block_without_our_words",
        "test_clarification::test_review_canaries_never_leave_through_a_reply_or_its_question",
    ],
}

# D-35 (019, 018 sections 15 to 17): the selection-quality rules P3 implements. Not numbered cases; reported and
# gated with GATE-P3 like the S1 supporting evidence.
P3_SUPPORTING = {
    "D-35 question rules (gap, alternative route, screen)": [
        "test_clarification::test_p3_34_a_proposal_must_name_its_evidence_gap",
        "test_clarification::test_review_the_alternative_route_reaches_the_applicant",
        "test_clarification::test_create_question_refuses_unsafe_gaps_and_routes",
    ],
    "D-35 decision rationale and policy reference": [
        "test_decision::test_p3_44_a_decision_is_one_transaction_with_its_held_follow_on",
        "test_decision::test_review_the_selection_policy_setting_is_validated",
        "test_decision::test_d35_every_criterion_needs_capability_strength_and_a_note",
        "test_decision::test_review_no_evidence_means_capability_unknown",
    ],
    "D-35 human-only assessment": [
        "test_decision::test_d35_a_human_only_assessment_is_allowed_only_when_model_advice_is_unavailable",
        "test_decision::test_d35_human_only_is_never_a_shortcut_past_a_working_assessment",
        "test_decision::test_review_human_only_is_reachable_when_staff_get_the_case_back_without_a_reassessment",
        "test_decision::test_recheck_human_only_after_the_run_cap_in_assessing",
    ],
}


# P4 acceptance plan (021 section 12; GATE-P4, task 4C): each case names the tests that prove it, by the case
# numbers in their names plus the review tests that prove the same case. Reported and gated like S1, P2 and P3.
# GATE-P4 proves the synthetic agreement workflow against the Documenso fake; it is not a live-provider proof and
# does not approve real templates, real signing or custody of real documents (021 sections 15 to 18).
P4_CASES = {
    "TEST-P4-01": [
        "test_agreement_completion::test_p4_01_06_the_user_agreement_waits_for_the_ndas_gate",
        "test_p4_journey::test_p4_journey_the_default_gate_journey_over_http",
    ],
    "TEST-P4-02": [
        "test_agreement_completion::test_p4_13_02_a_webhook_never_verifies_and_duplicates_and_late_events_are_harmless",
        "test_agreement_completion::test_p4_31_a_stale_verification_or_changed_recipients_never_advance",
        "test_p4_journey::test_p4_removed_gate_a_status_write_without_a_fresh_read_is_refused",
    ],
    "TEST-P4-03": [
        "test_agreements::test_p4_03_a_duplicate_create_is_never_sent_one_envelope_per_instance",
        "test_agreements::test_p4_03_12_a_crash_after_the_exchange_reconciles_and_never_sends_again",
    ],
    "TEST-P4-04": [
        "test_agreement_custody::test_p4_04_19_the_default_gate_journey_ends_in_exactly_one_held_hand_off",
        "test_agreement_custody::test_p4_04_storage_refuses_an_unsafe_directory_and_a_repository_location",
        "test_agreement_custody::test_review_downloads_run_outside_any_transaction_and_reads_open_the_file_once",
        "test_agreement_custody::test_p4_27_corruption_or_an_unsafe_file_refuses_and_opens_a_staff_item",
    ],
    "TEST-P4-05": [
        "test_agreement_custody::test_p4_05_the_user_agreement_waits_for_confirmed_required_details",
        "test_agreement_custody::test_review_an_nda_that_needs_details_starts_once_they_are_confirmed",
        "test_p4_journey::test_p4_details_are_visible_only_to_those_who_confirm_them",
    ],
    "TEST-P4-06": [
        "test_agreement_completion::test_p4_01_06_the_user_agreement_waits_for_the_ndas_gate",
        "test_agreement_completion::test_p4_06_an_advance_that_cannot_issue_opens_a_staff_item",
        "test_agreement_recovery::test_d43_the_d15_backstop_ignores_a_replaced_nda",
        "test_p4_journey::test_p4_journey_the_default_gate_journey_over_http",
    ],
    "TEST-P4-07": [
        "test_agreement_custody::test_p4_07_a_custody_outage_leaves_signing_verified_and_blocks_only_progression",
        "test_agreement_custody::test_p4_07_a_non_pdf_is_never_stored",
        "test_agreement_custody::test_p4_07_an_interruption_between_the_file_and_the_record_leaves_one_authoritative_copy",
        "test_agreement_custody::test_review_a_stored_copy_is_never_replaced_by_a_retry_and_a_collision_goes_to_staff",
        "test_agreement_custody::test_review_a_changed_envelope_during_custody_fails_custody_and_stores_nothing",
        "test_p4_journey::test_p4_removed_gate_the_hand_off_refuses_without_custody",
    ],
    "TEST-P4-08": [
        "test_agreement_completion::test_p4_08_webhook_authentication_and_uniform_answers",
        "test_agreement_completion::test_p4_08_the_route_is_mounted_only_in_test_and_development",
        "test_agreement_completion::test_p4_08_every_secret_is_compared_and_csrf_does_not_block_the_provider",
    ],
    "TEST-P4-09": [
        "test_agreements::test_p4_09_activation_releases_only_eligible_held_issue_nda",
        "test_agreements::test_p4_09_the_command_needs_a_real_approval_reference",
        "test_agreements::test_p4_09_a_refusal_returns_issue_nda_to_held_without_using_up_its_attempts",
        "test_p4_journey::test_p4_09_activation_refuses_a_non_admitted_application_and_never_releases_other_held_kinds",
    ],
    "TEST-P4-10": ["test_agreements::test_p4_10_the_instance_and_its_key_are_committed_before_any_provider_call"],
    "TEST-P4-11": [
        "test_agreements::test_p4_11_an_unknown_create_reconciles_on_admissible_evidence",
        "test_agreements::test_p4_11_with_no_evidence_a_decision_maker_decides_and_p4_30_a_late_orphan_is_cancelled",
        "test_agreements::test_p4_11_abandon_cancels_the_instance_and_keeps_watching_the_key",
        "test_agreements::test_p4_11_duplicate_envelopes_for_one_key_go_to_staff_and_block_a_new_create",
        "test_agreements::test_p4_11_only_our_key_template_document_and_recipients_are_evidence",
        "test_agreements::test_p4_11_a_defect_during_the_exchange_is_an_unknown_outcome",
        "test_agreements::test_p4_11_a_reconciliation_that_cannot_finish_opens_a_staff_item",
    ],
    "TEST-P4-12": [
        "test_agreements::test_p4_12_distribute_rereads_first_and_never_distributes_twice",
        "test_agreements::test_p4_12_an_unknown_distribute_reconciles_without_a_second_send",
        "test_agreements::test_p4_12_a_distribute_still_unknown_after_the_settle_window_goes_to_a_decision_maker",
        "test_agreements::test_p4_12_a_pending_distribute_is_reconciled_before_a_later_refusal",
        "test_agreement_completion::test_p4_12_an_unknown_distribute_can_be_decided_and_redistributed",
    ],
    "TEST-P4-13": [
        "test_agreement_completion::test_p4_13_02_a_webhook_never_verifies_and_duplicates_and_late_events_are_harmless",
        "test_agreement_completion::test_p4_13_a_webhook_brings_the_read_forward_without_waiting_for_the_sweep",
        "test_agreement_completion::test_p4_13_a_completed_hint_never_moves_a_declined_or_unissued_instance",
        "test_agreement_recovery::test_hdg6_a_false_completion_hint_is_reset_by_the_read",
        "test_agreement_recovery::test_hdg6_a_hint_never_moves_an_instance_that_was_not_issued",
    ],
    "TEST-P4-14": [
        "test_agreement_completion::test_p4_14_a_lost_webhook_is_caught_by_the_sweep",
        "test_agreement_recovery::test_hdg6_a_lost_webhook_cannot_hide_a_late_completion_of_a_closed_instance",
    ],
    "TEST-P4-15": [
        "test_agreement_completion::test_p4_15_partial_rejection_expiry_and_cancellation",
        "test_agreement_completion::test_p4_15_a_declined_agreement_is_reissued_only_by_a_decision_maker",
    ],
    "TEST-P4-16": ["test_agreement_completion::test_p4_16_a_read_showing_another_envelope_key_or_template_never_verifies"],
    "TEST-P4-17": [
        "test_agreement_custody::test_p4_17_27_retrieval_is_audited_before_any_byte_and_served_as_an_attachment",
        "test_agreement_custody::test_review_outsiders_get_the_same_404_and_add_no_audit_rows",
    ],
    "TEST-P4-18": [
        "test_agreements::test_p4_18_a_429_is_honoured_and_a_down_provider_goes_to_staff",
        "test_agreements::test_p4_18_a_definite_rejection_goes_to_staff_without_a_retry",
        "test_agreements::test_p4_18_distribute_honours_a_429_and_reconciles_a_5xx",
        "test_agreement_completion::test_p4_18_reads_honour_a_429_and_a_down_provider_goes_to_staff",
        "test_agreement_completion::test_p4_18_the_sweep_survives_a_provider_outage",
    ],
    "TEST-P4-19": [
        "test_agreement_custody::test_p4_04_19_the_default_gate_journey_ends_in_exactly_one_held_hand_off",
        "test_p4_journey::test_p4_journey_the_default_gate_journey_over_http",
    ],
    "TEST-P4-20": [
        "test_agreements::test_p4_20_a_real_documenso_host_and_credentials_are_refused_outside_an_authorized_environment",
        "test_agreements::test_p4_20_the_agreement_guard_requires_a_test_host",
        "test_agreements::test_p4_20_all_problems_reports_agreement_settings_from_the_environment",
        "test_agreement_completion::test_p4_20_webhook_secrets_are_test_only_and_at_most_two",
    ],
    "TEST-P4-21": [
        "test_agreement_custody::test_p4_21_the_screen_shows_three_statuses_and_enforces_permissions",
        "test_agreement_custody::test_p4_21_actions_need_csrf_their_permission_and_keep_what_was_typed",
        "test_agreement_custody::test_p4_21_a_refused_integrity_disposition_keeps_the_typed_reason",
        "test_agreement_custody::test_review_malformed_identifiers_are_refused_not_a_server_error",
        "test_agreement_custody::test_review_no_consequential_choice_is_preselected_for_a_decision_maker",
        "test_p4_journey::test_p4_21_hostile_details_and_typed_reasons_are_escaped_on_the_screen_and_its_refusals",
    ],
    "TEST-P4-22": [
        "test_agreements::test_p4_22_a_pause_stops_create_and_distribute",
        "test_agreements::test_p4_22_a_pause_after_create_holds_the_distribute",
        "test_agreements::test_p4_22_reconciliation_runs_while_automation_is_paused",
        "test_agreement_completion::test_p4_22_reads_run_while_paused_but_the_sequence_waits_and_resume_does_not_burst",
    ],
    "TEST-P4-23": [
        "test_agreement_completion::test_p4_23_24_a_webhook_flood_makes_one_read_and_keeps_no_body_or_token",
        "test_agreement_completion::test_p4_23_hints_for_an_old_key_are_rate_limited",
        "test_agreement_recovery::test_hdg6_a_deeply_nested_webhook_body_gets_the_uniform_answer",
    ],
    "TEST-P4-24": [
        "test_agreements::test_p4_24_signing_tokens_and_links_are_never_stored_or_logged",
        "test_agreement_completion::test_p4_23_24_a_webhook_flood_makes_one_read_and_keeps_no_body_or_token",
        "test_p4_journey::test_p4_journey_the_default_gate_journey_over_http",
    ],
    "TEST-P4-25": [
        "test_agreements::test_p4_25_distribute_refuses_when_a_p2_send_check_fails",
        "test_agreements::test_p4_25_create_refuses_when_the_recipient_is_no_longer_the_verified_address",
        "test_agreements::test_p4_25_distribute_refuses_when_the_provider_recipients_differ",
        "test_agreements::test_p4_22_a_pause_after_create_holds_the_distribute",
    ],
    "TEST-P4-26": [
        "test_agreements::test_p4_26_protections_hold_for_every_role",
        "test_agreement_recovery::test_d42_d43_the_new_columns_are_set_once_for_every_role",
    ],
    "TEST-P4-27": [
        "test_agreement_custody::test_p4_17_27_retrieval_is_audited_before_any_byte_and_served_as_an_attachment",
        "test_agreement_custody::test_p4_27_denied_and_missing_look_the_same_and_are_both_recorded",
        "test_agreement_custody::test_p4_27_an_audit_failure_releases_nothing",
        "test_agreement_custody::test_p4_27_corruption_or_an_unsafe_file_refuses_and_opens_a_staff_item",
        "test_agreement_custody::test_review_unavailable_storage_refuses_without_blaming_the_document",
        "test_agreement_custody::test_review_retrieval_refuses_inside_a_transaction",
    ],
    "TEST-P4-28": [
        "test_agreements::test_p4_28_the_client_refuses_redirects_oversize_bad_tls_and_non_pdf",
        "test_agreements::test_p4_28_the_client_bounds_time_encoding_truncation_and_its_own_configuration",
    ],
    "TEST-P4-29": [
        "test_agreement_completion::test_p4_29_cancel_is_reconciled_at_the_provider_and_a_later_completion_goes_to_staff",
        "test_agreement_completion::test_p4_29_a_valid_completion_on_a_closed_instance_is_never_verified",
    ],
    "TEST-P4-30": [
        "test_agreements::test_p4_11_with_no_evidence_a_decision_maker_decides_and_p4_30_a_late_orphan_is_cancelled",
        "test_agreements::test_p4_30_a_late_draft_orphan_is_recorded_left_and_kept_open_for_staff",
        "test_agreements::test_p4_30_an_orphan_cancel_without_a_provider_goes_to_staff",
    ],
    "TEST-P4-31": [
        "test_agreement_completion::test_p4_31_a_stale_verification_or_changed_recipients_never_advance",
        "test_agreement_completion::test_p4_31_completion_with_changed_recipients_is_never_verified",
    ],
    "TEST-P4-32": [
        "test_agreement_completion::test_p4_32_withdrawal_during_agreements_cancels_every_live_envelope_and_issues_nothing_more",
        "test_agreement_completion::test_p4_32_stopping_before_the_envelope_exists_watches_an_unknown_create",
        "test_agreement_completion::test_p4_32_a_stop_during_a_running_distribute_is_recorded_and_the_sent_envelope_is_cancelled",
        "test_agreement_completion::test_p4_32_a_hold_is_resumable_and_a_withdrawal_is_final",
    ],
}

# D-41 to D-44 (011 section 4.1, 021 sections 15 to 17) and the hardening decisions taken during P4 (9kg.1 to 9kg.3,
# D-40 item D): not numbered cases; reported and gated with GATE-P4 like the S1 supporting evidence.
P4_SUPPORTING = {
    "D-41 provider email and the cancellation message": [
        "test_agreement_recovery::test_d41_provider_email_is_inventoried_and_the_cancellation_email_suppressed",
        "test_agreement_recovery::test_d41_the_suppression_is_sent_on_create_and_distribute",
    ],
    "D-42 hold, cancel and resume": [
        "test_agreement_recovery::test_d42_a_hold_cancels_a_partly_signed_envelope_and_resume_issues_a_new_instance",
        "test_agreement_recovery::test_d42_a_cancelled_agreement_is_never_reissued_without_a_decision_maker",
        "test_agreement_recovery::test_d42_withdrawal_is_not_resumable_and_a_verified_agreement_is_never_cancelled",
        "test_agreement_recovery::test_review_replace_never_issues_after_a_stop",
        "test_agreement_recovery::test_review_a_withdrawal_cannot_be_downgraded_to_a_resumable_hold",
        "test_agreement_recovery::test_review_resume_never_reissues_over_a_completion_after_cancel",
        "test_agreement_recovery::test_review_a_requested_cancel_closes_a_pending_create_without_calling_the_provider",
        "test_agreement_recovery::test_review_an_unknown_create_found_after_a_stop_is_kept_undistributed_and_watched",
        "test_agreement_recovery::test_review_protective_cancel_runs_while_paused_and_while_a_hard_bounce_is_open",
        "test_agreement_recovery::test_hdg6_cancel_uncertain_is_remedied_by_a_new_reconciled_cancel",
    ],
    "D-43 agreement integrity after verification": [
        "test_agreement_recovery::test_d43_a_changed_recipient_after_verification_holds_reliance_until_a_reasoned_resolution",
        "test_agreement_recovery::test_d43_replacement_makes_a_new_generation_eligible_and_keeps_the_verified_history",
        "test_agreement_recovery::test_review_a_user_agreement_is_not_reissued_while_the_nda_is_held",
        "test_agreement_recovery::test_review_replacing_a_user_agreement_waits_for_a_held_nda",
    ],
    "D-44 reconciliation while paused and bounded watches": [
        "test_agreement_recovery::test_d44_the_orphan_watch_ends_visibly_and_is_re_armed_a_bounded_number_of_times",
        "test_agreement_recovery::test_hdg6_the_closed_follow_up_ends_visibly",
        "test_agreement_recovery::test_hdg6_a_follow_up_read_keeps_the_minimum_interval_after_a_running_read",
        "test_agreement_recovery::test_hdg6_an_advance_that_keeps_failing_ends_with_a_staff_item",
        "test_agreement_recovery::test_hdg6_reissue_refuses_a_superseded_instance_and_reports_an_unverified_contact",
    ],
    "9kg.1 correspondence evidence is append-only": [
        "test_outbound::test_9kg_1_an_approved_message_keeps_its_authorization_and_only_its_disposition_changes",
        "test_outbound::test_9kg_1_an_approved_template_version_is_final_and_may_only_retire_while_drafts_stay_free",
        "test_outbound::test_9kg_1_a_staff_item_resolution_is_append_only_for_every_role",
        "test_inbound::test_9kg_1_inbound_locations_are_append_only_for_every_role",
    ],
    "9kg.2 a system pause needs decision-maker review": [
        "test_processing::test_9kg_2_a_system_pause_resumes_only_by_a_decision_maker_with_a_reason_after_its_cause",
        "test_processing::test_9kg_2_a_staff_pause_cannot_be_resumed_past_a_system_cause_that_arrived_later",
    ],
    "9kg.3 a hard bounce blocks every send": [
        "test_processing::test_9kg_3_an_open_hard_bounce_holds_every_send_and_refuses_staff_bypasses",
        "test_processing::test_9kg_3_an_exchange_in_flight_still_reconciles_and_the_verification_send_is_held",
    ],
    "Removed gates fail (negative controls)": [
        "test_p4_journey::test_p4_removed_gate_a_status_write_without_a_fresh_read_is_refused",
        "test_p4_journey::test_p4_removed_gate_the_user_agreement_backstop_refuses_an_early_instance",
        "test_p4_journey::test_p4_removed_gate_the_hand_off_refuses_without_custody",
    ],
}



# P5 provisioning plan (023 section 9; GATE-P5, unsigned): each case names the tests that prove it (P5 task 5C).
# P5_SUPPORTING holds the P5 design rules that are not a numbered case; every test in the P5 files is mapped.
P5_CASES = {
    "TEST-P5-01": [
        "test_provisioning::test_p5_01_release_reads_afresh_and_creates_one_request_awaiting_the_approver",
        "test_provisioning::test_review_a_paused_application_is_refused_at_release_with_a_staff_item",
        "test_provisioning::test_review_without_an_adapter_nothing_is_committed_and_staff_are_told",
        "test_p5_journey::test_p5_01_only_the_owners_versioned_command_releases_and_nothing_starts_without_it",
    ],
    "TEST-P5-02": [
        "test_provisioning::test_p5_02_a_changed_agreement_at_the_provider_refuses_release_and_holds_reliance",
        "test_provisioning::test_p5_02_a_changed_prerequisite_after_approval_blocks_the_create_at_the_effect_boundary",
        "test_provisioning::test_review_pause_is_part_of_every_effect_boundary_and_a_dry_run_writes_nothing",
        "test_provisioning::test_review_a_changed_prerequisite_since_the_handoff_is_recorded_and_bound_into_the_new_approval",
        "test_provisioning::test_review_a_prerequisite_broken_in_the_database_then_repaired_releases_again_on_a_fresh_address",
        "test_p5_journey::test_p5_02_a_broken_prerequisite_refuses_at_approval_at_the_password_set_and_at_activation",
    ],
    "TEST-P5-03": [
        "test_credentials::test_p5_13_14_03_04_invite_set_activate_and_welcome",
        "test_credentials::test_p5_03_activation_waits_for_an_approved_welcome_and_never_on_a_sent_link_alone",
        "test_credentials::test_review_activation_needs_verified_provisioning_and_a_completed_setup",
        "test_credentials::test_review_a_refused_activation_can_be_retried_once_its_cause_is_fixed",
    ],
    "TEST-P5-04": [
        "test_credentials::test_p5_13_14_03_04_invite_set_activate_and_welcome",
        "test_p5_journey::test_p5_04_a_bounced_welcome_opens_a_staff_item",
    ],
    "TEST-P5-05": [
        "test_closure::test_p5_05_18_closing_an_active_member_revokes_access_and_deletes_nothing",
        "test_closure::test_review_closing_mid_flow_cancels_queued_work_and_settles_cleanly",
        "test_closure::test_p5_revocations_and_withdrawals_are_fixed_for_every_role",
    ],
    "TEST-P5-06": [
        "test_provisioning::test_p5_06_the_naming_rule_is_deterministic_and_refuses_role_and_unsafe_addresses",
        "test_provisioning::test_p5_06_a_collision_takes_the_next_suffix_and_an_exception_needs_review",
        "test_provisioning::test_p5_06_a_name_the_rule_cannot_form_waits_for_a_reviewed_exception",
        "test_provisioning::test_review_two_applicants_with_the_same_name_never_share_an_address",
    ],
    "TEST-P5-07": [
        "test_provisioning::test_p5_07_approval_binds_the_exact_address_limits_method_and_prerequisites",
        "test_provisioning_screen::test_p5_19_approving_through_the_screen_needs_csrf_and_the_digest_shown",
        "test_p5_journey::test_p5_07_every_approved_component_changes_what_the_approver_confirms",
    ],
    "TEST-P5-08": [
        "test_provisioning::test_p5_08_12_the_attempt_is_committed_then_an_absent_read_then_one_create_then_an_authoritative_read",
        "test_provisioning::test_p5_08_a_crash_after_the_exchange_is_reconciled_never_resent",
        "test_provisioning::test_review_a_failed_absent_read_sends_nothing_and_retries",
    ],
    "TEST-P5-09": [
        "test_provisioning::test_p5_09_an_unknown_create_is_reconciled_by_reading_and_staff_confirm_it_is_ours",
        "test_provisioning::test_p5_09_an_unknown_create_that_never_landed_runs_a_new_series_after_the_bounded_checks",
        "test_provisioning::test_p5_09_a_500_on_the_reconcile_read_is_unknown_never_absent",
        "test_provisioning::test_p5_09_a_mailbox_present_before_our_create_is_a_conflict_and_never_adopted",
        "test_provisioning::test_review_a_429_after_the_create_landed_is_unknown_never_a_rejection",
        "test_provisioning::test_review_a_conflict_after_our_own_unknown_create_is_reconciled_and_new_series_are_bounded",
    ],
    "TEST-P5-10": [
        "test_provisioning::test_p5_10_a_mailbox_created_by_someone_else_inside_the_window_is_a_conflict",
        "test_provisioning::test_p5_10_a_duplicate_create_action_never_creates_a_second_mailbox",
        "test_provisioning::test_review_serialization_one_open_create_per_request_in_the_database",
    ],
    "TEST-P5-11": [
        "test_provisioning::test_p5_11_the_checklist_verifier_must_differ_from_the_creator_for_every_role",
    ],
    "TEST-P5-12": [
        "test_provisioning::test_p5_08_12_the_attempt_is_committed_then_an_absent_read_then_one_create_then_an_authoritative_read",
        "test_provisioning::test_p5_12_verification_needs_the_exact_mailbox_and_never_passes_on_anything_else",
    ],
    "TEST-P5-13": [
        "test_credentials::test_p5_13_14_03_04_invite_set_activate_and_welcome",
        "test_credentials::test_p5_13_used_expired_and_superseded_links_get_the_same_answer",
        "test_credentials::test_p5_13_mismatched_entries_change_nothing",
        "test_credentials::test_p5_13_a_definite_rejection_lets_the_applicant_choose_again_within_the_bound",
        "test_credentials::test_review_an_unused_link_expires_visibly_and_a_new_one_follows_then_staff_reissue",
        "test_credentials::test_review_a_completed_series_is_final_for_every_role",
    ],
    "TEST-P5-14": [
        "test_credentials::test_p5_13_14_03_04_invite_set_activate_and_welcome",
        "test_credentials::test_p5_14_an_uncertain_invitation_supersedes_and_is_bounded",
        "test_credentials::test_p5_14_a_recipient_changed_before_sending_cancels_the_invitation",
        "test_credentials::test_review_a_changed_contact_closes_a_link_already_sent",
        "test_credentials::test_review_an_invitation_is_never_sent_into_the_company_domain",
    ],
    "TEST-P5-15": [
        "test_credentials::test_p5_13_14_03_04_invite_set_activate_and_welcome",
        "test_credentials::test_p5_15_an_error_during_the_set_leaks_no_password_to_logs_or_the_page",
        "test_credentials::test_review_an_error_inside_the_recording_transaction_leaks_no_password",
        "test_credentials::test_review_the_setup_token_is_redacted_from_django_request_logs",
        "test_provisioning::test_review_the_generated_password_reaches_no_log_or_error",
    ],
    "TEST-P5-16": [
        "test_credentials::test_p5_16_an_unknown_password_outcome_blocks_activation_and_a_new_link_is_sent",
        "test_credentials::test_p5_16_a_set_that_never_returns_is_swept_to_uncertain",
    ],
    "TEST-P5-17": [
        "test_closure::test_p5_17_a_withdrawal_during_an_uncertain_create_recovers_the_late_mailbox_without_a_welcome",
        "test_closure::test_p5_17_rotation_waits_for_a_password_set_in_flight",
        "test_closure::test_review_a_late_mailbox_found_by_the_watch_is_recorded_honestly_never_as_not_applicable",
        "test_closure::test_review_a_stop_at_the_create_result_recovers_the_new_mailbox_and_revokes_it",
        "test_closure::test_review_a_stop_settles_when_the_create_fails_or_was_never_sent",
    ],
    "TEST-P5-18": [
        "test_closure::test_p5_05_18_closing_an_active_member_revokes_access_and_deletes_nothing",
        "test_closure::test_p5_18_unsupported_obligations_end_only_by_an_owner_accepted_exception",
        "test_closure::test_review_exceptions_cannot_waive_a_rotation_and_complete_the_rollup_only_when_settled",
        "test_closure::test_review_a_mailbox_present_before_our_create_is_never_touched_by_revocation",
        "test_closure::test_review_a_create_that_never_landed_settles_as_nothing_of_ours_only_after_its_watch",
        "test_closure::test_review_a_shared_forwarder_fixed_in_the_panel_is_verified_only_by_a_new_read",
        "test_p5_journey::test_p5_18_the_mail_host_adapter_has_no_delete_or_suspend_operation",
    ],
    "TEST-P5-19": [
        "test_provisioning_screen::test_p5_19_only_holders_of_a_provisioning_permission_open_the_screen_and_a_superuser_is_refused",
        "test_provisioning_screen::test_the_dossier_link_and_the_provisioning_screen_use_the_same_permissions",
        "test_provisioning_screen::test_p5_19_the_screen_shows_each_phase_the_next_action_and_its_owner",
        "test_provisioning_screen::test_p5_19_approving_through_the_screen_needs_csrf_and_the_digest_shown",
        "test_provisioning_screen::test_p5_19_a_refusal_keeps_what_was_typed_and_an_unknown_action_is_not_found",
        "test_provisioning_screen::test_p5_19_closing_through_the_screen_shows_revocation_and_the_owner_accepts_an_exception",
        "test_provisioning_screen::test_review_the_offer_table_per_status_and_method_matches_the_service_guards_as_written",
        "test_provisioning_screen::test_review_confirm_found_is_offered_exactly_when_the_service_accepts_it",
        "test_provisioning_screen::test_review_the_next_action_names_the_right_owner_for_each_status_and_method",
        "test_provisioning_screen::test_review_after_a_close_the_address_is_released_from_the_screen",
        "test_provisioning_screen::test_review_a_late_mailbox_on_a_superseded_request_is_decided_from_the_screen",
        "test_provisioning_screen::test_review_a_checklist_request_shows_its_operator_steps",
        "test_provisioning_screen::test_review_another_applications_records_are_never_acted_on",
        "test_provisioning_screen::test_review_every_refusal_is_logged_without_typed_values_and_the_gate_covers_posts",
        "test_provisioning_screen::test_review_a_refused_exception_keeps_its_note",
    ],
    "TEST-P5-20": [
        "test_provisioning_screen::test_p5_20_provisioning_permissions_grant_no_mail_or_document_access",
    ],
    "TEST-P5-21": [
        "test_closure::test_p5_21_get_shows_post_commits_and_the_link_works_once",
        "test_closure::test_p5_21_a_new_link_supersedes_the_old_one_and_a_changed_contact_closes_it",
        "test_closure::test_review_a_new_withdrawal_link_supersedes_one_still_sending",
        "test_p5_journey::test_p5_21_an_emailed_withdraw_only_creates_a_review_item",
    ],
    "TEST-P5-22": [
        "test_closure::test_p5_22_a_closed_application_is_never_closed_again_or_reopened",
        "test_closure::test_p5_22_closing_during_agreements_stops_unfinished_agreements",
        "test_closure::test_review_closing_during_agreements_cancels_the_unfinished_envelope",
        "test_p5_journey::test_p5_22_nothing_closes_an_application_for_want_of_a_response",
        "test_p5_journey::test_p5_22_a_new_application_after_a_withdrawal_inherits_nothing",
    ],
    "TEST-P5-23": [
        "test_provisioning::test_p5_23_a_real_adapter_domain_or_environment_value_is_refused",
        "test_provisioning::test_review_credential_like_notes_and_mail_host_keys_in_the_environment_are_refused",
        "test_provisioning::test_review_the_p2_mail_host_setting_in_the_environment_is_still_accepted",
    ],
    "TEST-P5-24": [
        "test_p5_journey::test_p5_24_the_journey_from_intake_to_activation_and_from_withdrawal_to_revocation_over_http",
    ],
}

P5_SUPPORTING = {
    "P5 records are append-only for every role": [
        "test_provisioning::test_p5_records_are_fixed_for_every_role",
        "test_credentials::test_p5_setups_are_fixed_for_every_role",
    ],
    "023 11.11 supersession and the bounded watch": [
        "test_provisioning::test_p5_superseding_a_request_without_a_mailbox_releases_the_address_and_awaits_a_new_approval",
        "test_provisioning::test_p5_superseding_after_a_mailbox_may_exist_keeps_the_address_and_watches_for_a_late_mailbox",
        "test_provisioning::test_review_a_clean_watch_end_releases_the_address_and_returns_the_stage",
        "test_provisioning::test_review_after_a_late_mailbox_the_stage_waits_for_the_watch_and_staff_release_the_address",
        "test_provisioning::test_review_supersede_waits_for_work_in_flight",
        "test_provisioning::test_review_a_definite_rejection_goes_to_staff_and_frees_the_address_without_a_watch",
        "test_provisioning::test_review_creates_that_keep_coming_back_not_created_stop_at_the_bound",
    ],
    "023 11.5 bounded credential recovery": [
        "test_credentials::test_review_definite_rejections_are_bounded",
        "test_credentials::test_review_a_change_can_be_superseded_while_a_link_is_outstanding",
        "test_credentials::test_review_staff_reissue_recovers_a_request_whose_contact_was_not_usable_at_first",
    ],
    "P5-D-6 the checklist credential is a separate contingency": [
        "test_credentials::test_review_the_checklist_path_never_calls_the_api_for_the_credential",
    ],
    "Removed gates fail (P5 negative controls)": [
        "test_p5_journey::test_p5_removed_gate_without_the_proof_of_ownership_revocation_would_rotate_someone_elses_mailbox",
        "test_p5_journey::test_p5_removed_gate_without_the_screen_gate_each_service_still_refuses",
    ],
}


# P6 staging plan (026 section 11; GATE-STAGING, signed D-50): each case names the tests that prove it in a full run
# (P6 task 6C). Most cases are also shown live on the staging stack by the drill scripts named in P6_EVIDENCE below
# (TEST-P6-27 only there: P6_LIVE_ONLY), whose results 026 section 16 records; a live script is not a pytest run, so
# it is evidence beside the gate, not part of it.
# P6_SUPPORTING holds the P6 tests that are design rules rather than a numbered case; every P6 test is mapped.
# For TEST-P6-08, 24, 25, 26 and 31 the mapped tests pin the code's shape (adapters, workflow, route sets); the
# behaviour is shown by the drills, so a PASS there is not behaviour evidence on its own (028 section 4). The
# evidence register (P6_EVIDENCE) carries that per case, so the report prints it instead of this comment.
P6_CASES = {
    "TEST-P6-01": [
        "test_image::test_6b5_the_base_image_is_the_digest_the_tests_run_on",
        "test_image::test_6b5_dependencies_are_hash_locked_and_the_process_is_not_root",
        "test_image::test_6b5_no_secret_reaches_a_layer",
        "test_staging_compose::test_6b5b_every_catalyst_container_is_locked_down_and_pinned_to_staging",
        "test_release::test_6b10_the_image_workflow_attests_only_main_and_pushes_nowhere",
        "test_staging_compose::test_6b5b_the_image_creates_the_mount_points_with_their_owners_and_modes",
    ],
    "TEST-P6-02": [
        "test_startup::test_6b2_staging_passes_django_deploy_checks",
    ],
    "TEST-P6-03": [
        "test_guards::test_only_development_test_and_staging_environments_are_allowed",
        "test_guards::test_6b1_staging_allows_the_fake_agreement_provider_only_under_the_test_rules",
        "test_guards::test_6b1_staging_allows_only_the_fake_mail_host_and_a_test_domain",
        "test_guards::test_6b1_staging_links_must_be_https_and_production_still_may_not_use_any_fake",
        "test_guards::test_6b1_staging_evidence_fixtures_are_no_wider_than_test",
        "test_guards::test_6b1_staging_keeps_the_test_model_only_and_no_live_mail_or_send_evidence",
        "test_guards::test_6b1_review_staging_never_prints_mail_and_its_file_sink_is_private",
        "test_guards::test_6b1_review_staging_refuses_a_private_mail_peer_like_development",
        "test_guards::test_6b1_review_staging_builds_only_the_test_model",
        "test_startup::test_6b2_staging_refuses_a_production_link_host",
        "test_startup::test_6b2_review_staging_refuses_wildcard_production_and_look_alike_hosts",
        "test_startup::test_6b5_a_deployment_cannot_call_itself_development",
    ],
    "TEST-P6-04": [
        "test_fetcher_role::test_9kg24_a_fetcher_process_must_connect_as_the_fetcher_role_and_run_only_the_fetch",
        "test_fetcher_role::test_9kg24_the_fetcher_role_reaches_nothing_else",
        "test_worker::test_6b5_a_worker_process_runs_only_the_kinds_it_is_given",
        "test_startup::test_6b5_review_the_web_process_never_runs_as_the_fetcher_or_without_a_signing_key",
        "test_startup::test_6b5_the_fetcher_starts_without_the_link_signing_key",
        "test_staging_compose::test_6b5b_each_process_mounts_only_its_own_secrets_and_its_own_database_password",
        "test_staging_compose::test_6b5b_no_secret_is_ever_in_an_environment_or_an_env_file",
        "test_fetcher_role::test_9kg24_the_fetcher_role_fetches_completes_collection_and_queues_the_assessment",
        "test_fetcher_role::test_9kg24_the_fetcher_role_records_retries_refusals_and_missing_pages",
        "test_fetcher_role::test_9kg24_a_compromised_fetcher_cannot_queue_replay_or_move_anything_outside_its_fetch",
    ],
    "TEST-P6-05": [
        "test_health::test_6b3_readiness_refuses_pending_migrations_a_wrong_role_and_a_dead_database",
    ],
    "TEST-P6-06": [
        "test_db_roles::test_6b6_staging_provisioning_takes_passwords_only_from_files",
        "test_db_roles::test_6b6_staging_provisioning_succeeds_from_files_and_stores_only_password_hashes",
        "test_db_roles::test_6b6_reversing_the_grant_migration_revokes_and_reapplying_restores_it",
    ],
    "TEST-P6-07": [
        "test_health::test_6b3_liveness_answers_ok_without_touching_the_database",
        "test_health::test_6b3_readiness_is_a_fixed_token_with_no_version_or_detail",
        "test_health::test_6b3_readiness_refuses_pending_migrations_a_wrong_role_and_a_dead_database",
        "test_health::test_6b3_readiness_runs_the_strict_web_role_check",
        "test_health::test_6b3_health_answers_only_on_the_local_hosts",
        "test_health::test_6b3_readiness_is_cached_briefly_so_probes_cannot_load_the_database",
    ],
    "TEST-P6-08": [
        "test_release::test_6b10_the_adapters_take_only_content_references_and_smoke_through_the_readiness_cache",
        "test_release::test_6b10_forward_only_migrations_block_only_an_image_that_does_not_know_them",
    ],
    "TEST-P6-09": [
        "test_release::test_6b10_an_image_lists_its_migrations_with_no_settings_and_no_database",
        "test_release::test_6b10_forward_only_migrations_block_only_an_image_that_does_not_know_them",
        "test_release::test_6b10_every_contracting_migration_is_marked_forward_only_or_reviewed_as_safe",
        "test_release::test_6b10_the_contracting_scan_sees_a_removed_field_and_ignores_a_new_table",
        "test_release::test_6b10_the_release_apps_are_every_first_party_app",
        "test_release::test_6b10_the_blockers_command_is_the_tested_function",
    ],
    "TEST-P6-10": [
        "test_release::test_6b10_release_facts_read_back_from_the_database",
        "test_release::test_9kg_37_the_gate_allows_only_the_approved_image_with_its_backup_bound_and_the_recorded_revert",
        "test_release::test_9kg_37_the_operation_commands_are_the_tested_functions",
        "test_release::test_9kg_37_the_adapters_gate_on_the_operation_before_switching_and_the_smoke_decides_the_receipt",
    ],
    "TEST-P6-11": [
        "test_startup::test_6b5_staging_reads_each_secret_from_its_own_file",
        "test_startup::test_6b5_staging_refuses_a_secret_in_the_environment",
        "test_startup::test_6b5_every_secret_name_is_both_read_and_guarded",
        "test_startup::test_6b5_secret_files_keep_their_own_spaces_and_lose_only_the_line_ending",
        "test_startup::test_6b5_an_unreadable_secret_stops_start_up_without_showing_its_bytes",
        "test_startup::test_6b5_staging_refuses_a_missing_secrets_directory_or_file",
        "test_staging_compose::test_6b5b_no_secret_is_ever_in_an_environment_or_an_env_file",
        "test_secret_rotation::test_6b10a_a_rotated_role_password_takes_effect_and_the_old_one_stops_working",
        "test_staging_compose::test_6b5b_the_committed_compose_file_is_exactly_the_rendering",
    ],
    "TEST-P6-12": [
        "test_staging_proxy::test_6b8_the_public_site_serves_only_the_applicant_routes",
        "test_staging_proxy::test_6b8_every_token_bearing_route_is_a_private_path",
        "test_cutover::test_6b11_r1_and_r2_together_are_every_applicant_route_and_nothing_more",
        "test_staging_compose::test_6b5b_each_port_is_exactly_one_caddy_server",
    ],
    "TEST-P6-13": [
        "test_staging_proxy::test_6b8_token_segments_are_redacted_in_every_log_including_errors",
        "test_image::test_6b5_the_web_process_writes_no_access_log_and_listens_only_on_a_private_unix_socket",
        "test_staging_compose::test_6b5b_the_database_never_logs_statements_or_parameters",
        "test_cutover::test_6b11_the_learn_log_snippet_is_the_rendering_and_redacts_every_token_path",
    ],
    "TEST-P6-14": [
        "test_web_security::test_6b2_plain_http_is_redirected_to_https_except_the_health_paths",
        "test_web_security::test_6b2_hsts_is_sent_only_over_https_and_covers_no_subdomains",
        "test_web_security::test_6b2_the_csrf_cookie_is_host_only_secure_and_hidden_from_scripts",
        "test_web_security::test_6b2_every_page_carries_the_csp_and_framing_headers",
        "test_web_security::test_6b2_an_anonymous_page_creates_no_session",
        "test_startup::test_6b2_staging_cookies_are_secure_host_only_and_sessions_idle_out",
        "test_staging_proxy::test_6b8_caddy_trusts_no_proxy_and_sets_the_forwarded_values_itself",
        "test_staging_proxy::test_6b8_caddy_responses_carry_safe_headers_and_slow_clients_time_out",
        "test_cutover::test_6b11_the_snippets_overwrite_the_forwarded_headers_and_default_to_the_web_socket",
        "test_web_security::test_6b2_an_idle_staff_session_is_refused_after_30_minutes",
        "test_startup::test_6b2_local_environments_keep_plain_cookies_but_still_idle_out",
    ],
    "TEST-P6-15": [
        "test_staff_two_factor::test_6b9_two_factor_is_required_outside_the_local_environments",
        "test_staff_two_factor::test_6b9_the_login_needs_the_token_and_a_verified_session_reaches_every_staff_page",
        "test_staff_two_factor::test_6b9_an_unverified_staff_session_reaches_no_staff_page",
        "test_staff_two_factor::test_6b9_an_anonymous_request_reaches_only_the_login_page",
        "test_staff_two_factor::test_6b9_a_superuser_account_gets_no_staff_session_where_two_factor_is_required",
        "test_staging_proxy::test_6b8_the_staff_site_binds_privately_and_carries_only_staff_and_static",
        "test_staging_compose::test_6b5b_the_staff_site_is_published_only_on_a_named_private_address",
        "test_staff_two_factor::test_6b9_a_recovery_code_signs_in_once",
        "test_staff_two_factor::test_6b9_a_session_older_than_its_absolute_lifetime_is_ended",
        "test_staff_two_factor::test_6b9_a_session_without_a_recorded_login_time_is_ended",
        "test_staff_two_factor::test_6b9_expired_sessions_are_removed_by_a_self_renewing_action",
        "test_staff_two_factor::test_6b9_health_reports_an_unscheduled_clean_up_where_two_factor_is_required",
        "test_staff_two_factor::test_6b9_repeated_password_failures_lock_the_username_even_for_the_right_password",
        "test_staff_two_factor::test_6b9_superusers_keep_their_local_sessions_in_test_and_development",
        "test_staff_two_factor::test_6b9_the_application_role_may_count_failures_but_never_change_or_add_a_device",
        "test_staff_two_factor::test_6b9_the_break_glass_reset_leaves_nothing_from_before_it_working",
        "test_staff_two_factor::test_6b9_the_login_page_locks_a_username_that_does_not_exist_like_one_that_does",
    ],
    "TEST-P6-16": [
        "test_staging_proxy::test_6b8_there_is_no_webhook_site",
        "test_agreement_completion::test_p4_08_webhook_authentication_and_uniform_answers",
        "test_agreement_completion::test_p4_08_every_secret_is_compared_and_csrf_does_not_block_the_provider",
        "test_agreement_completion::test_p4_20_webhook_secrets_are_test_only_and_at_most_two",
    ],
    "TEST-P6-17": [
        "test_system_health::test_6b4_a_dead_worker_is_reported_and_recovery_clears_it",
        "test_staging_alerts::test_6b12_a_stopped_worker_and_an_unreachable_form_are_reported",
        "test_staging_alerts::test_6b12_recovery_is_noted_once_and_retried_if_the_note_failed",
        "test_system_health::test_6b4_the_heartbeat_is_written_atomically_and_never_stops_the_worker",
        "test_system_health::test_6b4_the_worker_beats_while_it_runs",
        "test_system_health::test_6b4_a_lease_renewal_also_beats_the_heartbeat",
        "test_system_health::test_6b4_a_quiet_system_is_healthy",
        "test_startup::test_6b4_review_staging_requires_a_worker_heartbeat_file",
        "test_staging_alerts::test_6b12_a_healthy_report_sends_nothing_and_leaves_the_marker",
    ],
    "TEST-P6-18": [
        "test_inbound::test_p2_41_g1_reports_a_healthy_collector_and_a_broken_chain",
        "test_inbound::test_p2_41_g1_reports_a_stale_watermark",
        "test_staging_alerts::test_6b12_findings_are_codes_and_a_stale_heartbeat_is_urgent",
    ],
    "TEST-P6-19": [
        "test_outbound::test_p2_a7_an_uncertain_send_without_an_unknown_attempt_reaches_staff",
        "test_system_health::test_6b4_an_aged_hard_bounce_alerts_and_a_fresh_one_does_not",
        "test_system_health::test_6b4_agreement_and_custody_states_alert",
        "test_system_health::test_6b4_a_backlog_and_an_expired_lease_are_anomalies",
        "test_system_health::test_6b4_a_conflict_alerts_until_staff_resolve_it_then_the_system_is_healthy",
        "test_system_health::test_6b4_a_revocation_round_that_never_ran_is_reported",
        "test_system_health::test_6b4_an_unknown_mailbox_create_is_reported_until_staff_resolve_it",
        "test_system_health::test_6b4_routine_staff_waiting_alerts_only_when_overdue",
    ],
    "TEST-P6-20": [
        "test_staging_alerts::test_6b12_the_sweep_is_quiet_while_the_health_check_is_fresh",
        "test_staging_alerts::test_6b12_the_sweep_alerts_when_the_health_check_is_stale_or_never_ran",
        "test_staging_alerts::test_6b12_a_check_that_fails_without_a_report_is_never_healthy",
        "test_system_health::test_6b4_a_malformed_report_is_a_failed_check_not_a_finding",
        "test_system_health::test_6b4_a_failing_check_exits_2_and_never_reports_a_finding",
    ],
    "TEST-P6-21": [
        "test_backup_commands::test_6b7_a_backup_restores_elsewhere_byte_for_byte_with_its_files_and_a_hold",
        "test_backup_commands::test_6b7_a_failed_backup_leaves_no_set_that_looks_usable",
        "test_backup_commands::test_6b13_a_failed_backup_keeps_the_previous_good_set_intact",
        "test_db_roles::test_6b6_the_backup_role_reads_every_table_but_sessions_and_writes_nothing",
        "test_db_roles::test_6b6_the_backup_role_can_read_but_never_change_history",
        "test_db_roles::test_6b6_the_backup_role_reads_every_sequence_and_can_never_draw_or_set_one",
        "test_staging_alerts::test_6b13_a_stale_backup_and_an_overdue_restore_drill_are_reported",
        "test_staging_alerts::test_6b13_a_missing_or_empty_receipt_directory_counts_as_stale",
    ],
    "TEST-P6-22": [
        "test_restore_rehearsal::test_9kg_7_backup_restore_elsewhere_and_verify_rows_files_roles_and_triggers",
        "test_backup_commands::test_6b7_the_worker_claims_nothing_while_the_restore_hold_is_present",
        "test_backup_commands::test_6b7_the_application_role_cannot_lift_the_restore_hold",
        "test_post_restore::test_6b7b_lifting_needs_a_review_run_and_both_confirmations",
        "test_staging_alerts::test_6b13_a_failed_drill_never_counts_as_a_drill_done",
        "test_staging_alerts::test_6b13_a_stale_backup_and_an_overdue_restore_drill_are_reported",
    ],
    "TEST-P6-23": [
        "test_backup_commands::test_6b7_a_damaged_set_is_refused_before_anything_loads",
        "test_backup_commands::test_6b7_a_restore_never_touches_a_database_that_is_in_use_or_not_named",
        "test_backup_commands::test_6b7_a_tampered_or_world_readable_set_is_refused",
        "test_backup_commands::test_6b7_a_bad_set_name_is_refused",
        "test_backup_commands::test_6b7_a_target_at_other_migrations_is_refused",
        "test_restore_rehearsal::test_9kg_7_the_checker_refuses_a_relative_or_missing_directory",
        "test_post_restore::test_6b7b_refuses_without_a_hold_or_a_named_database",
    ],
    "TEST-P6-24": [
        "test_release::test_6b10_the_adapters_take_only_content_references_and_smoke_through_the_readiness_cache",
        "test_release::test_9kg_37_an_operation_binds_only_a_backup_taken_for_it_and_refuses_a_stale_or_missing_one",
        "test_release::test_9kg_37_a_restarted_operation_takes_a_new_backup_and_bad_ids_or_commits_are_refused",
        "test_release::test_9kg_37_the_gate_allows_only_the_approved_image_with_its_backup_bound_and_the_recorded_revert",
    ],
    "TEST-P6-25": [
        "test_release::test_6b10_forward_only_migrations_block_only_an_image_that_does_not_know_them",
        "test_release::test_9kg_38_the_drill_reverts_n_plus_one_to_n_on_the_expanded_schema_and_refuses_the_contract_revert",
        "test_restore_rehearsal::test_9kg_7_backup_restore_elsewhere_and_verify_rows_files_roles_and_triggers",
    ],
    "TEST-P6-26": [
        "test_cutover::test_6b11_r2_is_exactly_the_token_return_paths",
        "test_cutover::test_6b11_r1_is_exactly_the_entry_pages_the_staging_proxy_serves",
        "test_cutover::test_6b11_r1_and_r2_together_are_every_applicant_route_and_nothing_more",
    ],
    "TEST-P6-28": [
        "test_staging_compose::test_6b5b_the_socket_is_shared_only_with_the_proxy_and_only_the_proxy_has_an_open_network",
        "test_guards::test_6b1_staging_links_must_be_https_and_production_still_may_not_use_any_fake",
        "test_guards::test_6b1_staging_keeps_the_test_model_only_and_no_live_mail_or_send_evidence",
    ],
    "TEST-P6-29": [
        "test_post_restore::test_6b7b_links_from_before_the_restore_stop_working_the_negative_control",
        "test_post_restore::test_6b7b_staff_passwords_and_sessions_from_before_the_restore_never_return",
        "test_post_restore::test_6b7b_withdrawal_links_close_and_in_flight_password_sets_become_unknown",
        "test_post_restore::test_6b7b_unfinished_access_removal_gets_one_new_round",
        "test_post_restore::test_6b7b_the_report_lists_outward_actions_and_running_ones_are_recovered",
    ],
    "TEST-P6-30": [
        "test_egress::test_6b11_the_policy_refuses_anything_but_a_connect_to_a_name_on_an_allowed_port",
        "test_egress::test_6b11_the_fixture_address_is_admitted_only_in_a_synthetic_environment",
        "test_egress::test_6b11_a_name_resolving_to_any_denied_address_is_refused_by_the_live_proxy",
        "test_egress::test_6b11_a_single_label_name_is_refused_before_any_lookup",
        "test_egress::test_6b11_evidence_is_fetched_through_the_egress_proxy",
        "test_egress::test_6b11_a_proxy_refusal_is_a_refusal_and_never_retried",
        "test_egress::test_6b11_the_proxy_refuses_to_start_with_a_fixture_outside_a_synthetic_environment",
        "test_egress::test_6b11_numeric_names_are_never_names",
        "test_egress::test_6b11_a_tunnel_whose_peer_stops_reading_is_bounded",
        "test_startup::test_6b11_a_staging_fetcher_refuses_to_start_without_the_egress_proxy",
        "test_fetcher_role::test_9kg24_the_fetcher_role_reaches_nothing_else",
    ],
    "TEST-P6-31": [
        "test_release::test_6b10_the_image_workflow_attests_only_main_and_pushes_nowhere",
        "test_release::test_6b10_the_adapters_take_only_content_references_and_smoke_through_the_readiness_cache",
    ],
    "TEST-P6-32": [
        "test_health::test_6b3_staff_answer_only_on_the_staff_host_once_one_is_named",
        "test_health::test_6b3_health_answers_only_on_the_local_hosts",
        "test_health::test_6b3_a_bad_host_header_is_a_400_not_a_server_error",
        "test_startup::test_6b3_review_staging_needs_a_proper_staff_host_and_local_hosts",
        "test_startup::test_6b8_the_staff_host_is_never_also_a_local_health_host",
    ],
    "TEST-P6-33": [
        "test_staging_proxy::test_6b8_the_committed_caddyfile_is_exactly_the_rendering",
        "test_staging_proxy::test_6b8_every_token_bearing_route_is_a_private_path",
        "test_staging_compose::test_6b5b_the_database_never_logs_statements_or_parameters",
    ],
    "TEST-P6-34": [
        "test_agreement_completion::test_p4_13_02_a_webhook_never_verifies_and_duplicates_and_late_events_are_harmless",
        "test_agreement_completion::test_p4_23_24_a_webhook_flood_makes_one_read_and_keeps_no_body_or_token",
    ],
    "TEST-P6-35": [
        "test_system_health::test_6b4_the_report_never_carries_applicant_data",
        "test_backup_commands::test_6b7_a_database_error_reports_only_its_class_and_code_never_the_row",
        "test_backup_commands::test_6b7_a_tampered_or_world_readable_set_is_refused",
        "test_staging_alerts::test_6b12_an_alert_carries_signal_codes_and_nothing_else",
        # 9kg.40: the scan over committed evidence, receipts, alert text and the deployment receipt
        "test_personal_data_scan::test_9kg40_a_planted_sentinel_in_each_input_class_fails_the_scan_and_the_value_is_never_printed",
        "test_personal_data_scan::test_9kg40_an_undecodable_stdin_is_reported_with_a_fixed_message_never_its_bytes",
        "test_personal_data_scan::test_9kg40_the_scan_fails_closed_on_zero_files_or_an_unreadable_input",
        "test_personal_data_scan::test_9kg40_the_committed_evidence_passes_the_scan",
        "test_personal_data_scan::test_9kg40_reserved_addresses_digests_run_ids_paths_and_ranges_are_not_personal_data",
        "test_personal_data_scan::test_9kg40_email_and_token_patterns_catch_what_fixture_names_alone_would_miss",
        "test_personal_data_scan::test_9kg40_a_value_split_across_a_wrapped_line_is_found_at_the_paragraphs_first_line",
        "test_personal_data_scan::test_9kg40_every_fixture_person_name_is_on_the_scans_list_and_matched_whatever_its_case",
        "test_personal_data_scan::test_9kg40_every_filed_document_of_an_evidence_class_is_in_the_scanned_set",
        "test_personal_data_scan::test_9kg40_the_host_receipt_step_blocks_on_a_hit_and_keeps_no_receipt",
        "test_personal_data_scan::test_9kg40_the_receipt_step_scans_before_the_receipt_counts",
    ],
    "TEST-P6-36": [
        "test_secret_rotation::test_6b10a_a_routine_link_key_rotation_keeps_links_in_hand_working_while_the_old_key_is_a_fallback",
        "test_secret_rotation::test_6b10a_after_a_leak_the_old_links_fail_and_every_outstanding_one_is_closed_for_reissue",
        "test_secret_rotation::test_6b10a_closing_links_refuses_while_the_leaked_key_is_still_the_link_key",
        "test_secret_rotation::test_6b10a_password_links_are_not_signed_with_the_link_key_and_survive_its_rotation",
        "test_secret_rotation::test_6b10a_closing_links_refuses_while_a_fallback_key_remains_or_for_another_database",
        "test_secret_rotation::test_6b10a_rotating_the_django_secret_key_ends_every_staff_session",
        "test_secret_rotation::test_6b10a_a_rotated_role_password_takes_effect_and_the_old_one_stops_working",
        "test_agreement_completion::test_p4_08_every_secret_is_compared_and_csrf_does_not_block_the_provider",
    ],
    "TEST-P6-37": [
        "test_image::test_6b5_the_build_context_excludes_tests_history_and_the_tracker",
        "test_release::test_6b10_the_image_workflow_attests_only_main_and_pushes_nowhere",
    ],
    "TEST-P6-38": [
        "test_staging_alerts::test_6b12_an_alert_carries_signal_codes_and_nothing_else",
        "test_system_health::test_6b4_the_report_never_carries_applicant_data",
    ],
}

P6_SUPPORTING = {
    "9kg.2 a system pause resumes only past its cause (pre-staging hardening)": [
        "test_processing::test_9kg_2_every_system_pause_reason_is_a_resumable_cause_with_a_resolution",
        "test_processing::test_9kg_2_the_screen_offers_a_system_resume_only_to_a_decision_maker_with_a_required_reason",
    ],
    "9kg.51 every unbounded wait has an age bound in the health report (029 section 5.2)": [
        "test_system_health::test_9kg_51_each_aged_wait_raises_its_code_and_clears_when_resolved",
        "test_system_health::test_9kg_51_thresholds_and_paging_are_per_wait_class",
        "test_system_health::test_9kg_51_the_default_page_list_is_the_three_bad_classes_and_the_authority_flag_is_reported",
    ],
    "9kg.30 the staff role matrix, the grant command and the append-only grant record (029 section 17.1)": [
        "test_staff_roles::test_every_permission_a_staff_screen_checks_has_a_grant_path",
        "test_staff_roles::test_each_group_role_confers_exactly_its_matrix_set",
        "test_staff_roles::test_the_direct_roles_are_never_carried_by_a_group_and_the_decision_needs_the_authority",
        "test_staff_roles::test_superusers_unknown_roles_drifted_groups_and_a_missing_approval_are_refused",
        "test_staff_roles::test_the_grant_record_is_append_only_for_every_role_and_names_no_secret",
        "test_staff_roles::test_a_role_granted_by_the_command_opens_exactly_its_screens",
        "test_staff_roles::test_no_runbook_or_design_step_grants_with_raw_sql_or_a_shell",
        "test_staff_roles::test_every_group_membership_has_a_latest_grant_row",
    ],
    "9kg.50 the hold exit through the decision service and the staff verification resend (018 section 19, 016 section 10.14)": [
        "test_hold_and_resend::test_an_on_hold_case_comes_back_to_a_decision_through_the_service",
        "test_hold_and_resend::test_an_on_hold_case_comes_back_through_the_decision_form_and_a_refused_user_sees_403",
        "test_hold_and_resend::test_a_human_only_hold_can_also_leave_through_the_form",
        "test_hold_and_resend::test_staff_resend_supersedes_the_challenge_and_sends_the_same_message",
        "test_hold_and_resend::test_a_resend_is_refused_beyond_the_limit_after_verification_and_without_the_permission",
        "test_hold_and_resend::test_a_resend_is_refused_while_a_hard_bounce_is_open",
        "test_hold_and_resend::test_the_dossier_flags_a_case_awaiting_decision_or_on_hold_and_links_the_decision_screen",
    ],
    "oc4.12 the human-only assessment path completed for a launch with model advice disabled (018 section 20)": [
        "test_human_only::test_the_decision_service_and_screen_never_import_the_model_layer",
        "test_human_only::test_a_run_refused_under_the_suspension_is_labelled_so_and_leaves_assessing_through_the_decision_form",
        "test_human_only::test_a_capped_snapshot_leaves_assessing_through_the_decision_form_and_no_close_action_exists",
        "test_human_only::test_the_digest_carries_the_policy_and_a_bound_policy_still_records_the_pack_and_rubric",
        "test_human_only::test_the_guard_refuses_a_policy_that_is_unbound_or_bound_to_a_synthetic_pack",
        "test_human_only::test_a_human_only_decision_never_rests_on_free_text_alone",
        "test_human_only::test_human_only_decisions_are_counted_on_the_scorecard_without_identifiers",
        "test_human_only::test_model_output_is_shown_as_nonbinding",
        "test_human_only::test_the_evidence_manifest_names_every_state_and_a_new_failed_run_changes_the_digest",
        "test_human_only::test_a_paused_application_under_the_suspension_is_refused_at_once_not_requeued",
    ],
    "9kg.47 staff screens for the shell-only agreement states (021 section 20)": [
        "test_agreement_screens::test_an_unknown_create_is_decided_on_the_screen_and_refused_without_the_permission",
        "test_agreement_screens::test_an_unknown_distribute_is_decided_on_the_screen_and_cancelling_needs_the_manage_permission",
        "test_agreement_screens::test_an_unknown_cancel_is_decided_on_the_screen_and_refused_without_the_permission",
        "test_agreement_screens::test_a_template_version_is_approved_on_its_own_screen_by_the_digest_shown",
        "test_agreement_screens::test_agreement_items_point_at_the_agreements_screen",
        "test_agreement_screens::test_the_screen_refuses_a_reconciliation_in_progress_a_signed_and_an_observed_complete_agreement",
        "test_agreement_screens::test_the_cancel_button_is_absent_for_verified_cancelled_and_superseded_rows",
        "test_agreement_screens::test_a_second_template_version_becomes_current_and_a_repeat_approval_is_a_no_op",
        "test_agreement_screens::test_a_withdrawal_stops_an_agreement_the_provider_reports_complete_but_unverified",
    ],
    "9kg.6 the pause row is cleared only by an audited resume (database guard)": [
        "test_pause_guard::test_9kg6_a_bare_delete_or_update_by_the_application_role_is_refused",
        "test_pause_guard::test_9kg6_the_migration_owner_is_refused_the_same_way_and_truncate_is_refused_for_every_role",
        "test_pause_guard::test_9kg6_a_system_pause_clears_only_with_a_staff_resume_event_with_a_note_in_the_same_transaction",
        "test_pause_guard::test_9kg6_a_staff_pause_clears_with_the_resume_event_even_inside_a_savepoint",
        "test_pause_guard::test_9kg6_no_earlier_event_and_no_rolled_back_savepoint_event_clears_a_staff_pause",
        "test_pause_guard::test_9kg6_an_unknown_subject_type_is_guarded_and_cannot_be_cleared",
        "test_pause_guard::test_9kg6_the_transaction_marker_is_on_no_read_surface",
        "test_pause_guard::test_9kg6_the_event_transaction_marker_is_always_the_databases_own",
        "test_pause_guard::test_9kg6_the_supported_resume_path_clears_the_pause_and_work_resumes",
        "test_pause_guard::test_9kg6_the_restore_hold_keeps_its_own_rule",
    ],
    # PL-A batch item 1 (029 section 13.3): the public endpoints' limits with the proxy's client identity.
    "9kg.29 every public endpoint is limited per client and per subject, keyed on the proxy's client identity": [
        "test_throttle::test_9kg_29_the_client_identity_is_exactly_one_address_literal",
        "test_throttle::test_9kg_29_the_identity_source_is_the_proxy_header_or_the_peer_and_is_fixed_in_code",
        "test_throttle::test_9kg_29_every_public_endpoint_refuses_a_client_burst_uniformly_and_admits_again_after_the_window",
        "test_throttle::test_9kg_29_intake_is_keyed_on_the_hashed_address_and_the_address_bucket_limits_issuance_not_confirmation",
        "test_throttle::test_9kg_29_link_endpoints_are_keyed_on_the_client_and_the_token_hash_and_an_unknown_token_is_refused_alike",
        "test_throttle::test_9kg_29_the_forwarded_identity_counts_only_in_proxy_mode_and_a_missing_or_invalid_one_refuses_issuance",
        "test_throttle::test_9kg_29_an_unavailable_throttle_store_fails_closed_for_issuance_and_open_for_reading",
        "test_throttle::test_9kg_29_the_webhook_is_limited_per_client_before_the_secret_is_compared",
        "test_throttle::test_9kg_29_stale_buckets_are_swept_with_the_staff_sessions",
    ],
    # PL-A batch item 1 (029 sections 4.1, 7 and 13.3): invitation-only intake, enforced server-side.
    "9kg.43 intake is invitation-only by default, enforced in the service, spent once at confirmation": [
        "test_invitation::test_9kg_43_the_shipped_default_is_invitation_only_and_the_mode_is_fixed_in_code",
        "test_invitation::test_9kg_43_an_uninvited_address_gets_exactly_the_invited_response_and_nothing_is_recorded",
        "test_invitation::test_9kg_43_an_invitation_is_spent_at_confirmation_once_and_the_applicant_stays_admitted_afterwards",
        "test_invitation::test_9kg_43_concurrent_confirmations_spend_the_invitation_once",
        "test_invitation::test_9kg_43_an_invitation_expires_by_the_database_clock_and_an_expired_one_refuses_confirmation",
        "test_invitation::test_9kg_43_issuance_is_an_owner_run_command_that_records_who_issued_it_and_nobody_else_can_change",
        "test_invitation::test_9kg_43_with_the_mode_off_the_public_intake_is_unchanged",
        "test_invitation::test_9kg_43_the_dossier_the_health_report_and_the_release_receipt_show_the_mode",
    ],
    # 030 Q8 and Q4 (D-51): the one-paragraph data notice as an owner-approved template, and the member-on-file flag.
    "9kg.52 the data notice renders from one approved template on the intake page and in the invitation mail, and the owner records a member's agreement on file": [
        "test_intake_notice::test_9kg_52_the_approved_notice_renders_on_the_intake_page_in_invitation_mode_with_its_version_and_digest",
        "test_intake_notice::test_9kg_52_an_unapproved_notice_is_marked_draft_outside_a_live_environment_and_withheld_in_one",
        "test_intake_notice::test_9kg_52_the_invitation_mail_carries_the_notice_and_the_invitation_records_its_version_and_digest",
        "test_intake_notice::test_9kg_52_the_wording_is_an_owner_approved_template_and_not_a_constant",
        "test_intake_notice::test_9kg_52_the_member_on_file_flag_is_recorded_only_by_the_owner_run_command_and_fixed_by_the_database",
        "test_intake_notice::test_9kg_52_the_dossier_shows_the_member_on_file_state",
    ],
    "9kg.5 the database freezes inbound provenance and outbound and reply-link identity for every role (internal-launch batch item 6)": [
        "test_provenance_freezes::test_9kg5_a_frozen_inbound_column_refuses_an_update_for_every_role",
        "test_provenance_freezes::test_9kg5_the_updatable_inbound_columns_still_update_through_the_application_role_and_the_owner",
        "test_provenance_freezes::test_9kg5_no_role_deletes_or_truncates_inbound_messages",
        "test_provenance_freezes::test_9kg5_the_audited_retention_path_anonymizes_the_personal_inbound_columns_and_nothing_else",
        "test_provenance_freezes::test_9kg5_a_frozen_outbound_identity_column_refuses_an_update_for_every_role",
        "test_provenance_freezes::test_9kg5_an_outbound_message_id_is_set_once",
        "test_provenance_freezes::test_9kg5_the_outbound_delivery_columns_still_update_and_the_owner_still_ages_an_attempt",
        "test_provenance_freezes::test_9kg5_no_role_deletes_or_truncates_outbound_attempts",
        "test_provenance_freezes::test_9kg5_the_audited_retention_path_anonymizes_an_outbound_recipient",
        "test_provenance_freezes::test_9kg5_a_reply_link_keeps_its_question_and_message_and_is_never_deleted",
        "test_provenance_freezes::test_9kg5_the_freeze_functions_are_owned_fixed_and_not_executable_by_the_application_role",
        "test_provenance_freezes::test_9kg5_the_freeze_migration_reverses_and_reapplies_and_keeps_the_rows",
    ],
    "6hl.10 the administrator login reaches only the role-provisioning step (internal-launch batch item 6)": [
        "test_db_roles::test_6hl10_the_test_process_holds_no_administrator_login",
        "test_db_roles::test_6hl10_the_probe_login_is_read_by_the_test_support_module_only",
        "test_db_roles::test_child_processes_do_not_receive_the_administrator_login",
    ],
}

# Cases with no pytest evidence of their own: shown only by a live script (026 section 16).
P6_LIVE_ONLY = {
    "TEST-P6-27": "scripts/staging_check.sh, the dark deploy",
}


# --- the evidence register (9kg.44) -------------------------------------------------------------------------------
#
# A gate count can be read as more than it proves: a PASS on a case whose tests pin only the code's shape, or a case
# whose live clauses are still open, prints like any other. The register records, per P6 case, how each clause is
# shown, so tests/conftest.py prints partial and live-only cases apart from PASS and writes register.json at the end
# of a full run for the go/no-go package. It is data the report reads, not prose: check_register() refuses a missing
# entry, an unknown proof type or drill, a partial case without its residual or boundary, and a non-pytest proof
# without a commit or run id; tests/test_acceptance.py checks it reproduces after-action report 028 section 4 (21
# proven, one of them on a stand-in, and 17 partly). Historical counts stay historical in the AARs.
#
# Entry fields (`evidence()` fills what may default; there are no optimistic defaults for the rest):
#   proofs       how the case is shown, in order: "pytest" (the gated run), ("drill", "scripts/<name>.sh") (a live
#                drill on the staging stack, recorded in 026 section 16; DRILLS carries its revision and record), or
#                ("inspected" | "canary" | "walkthrough", <what>, <commit or run id>, <record>). Default: ["pytest"].
#   pytest       what the gated tests show: "behaviour" (default) or "shape" (they pin the code's shape; the
#                behaviour is a drill's, so a PASS is not behaviour evidence on its own; 028 section 4).
#   environment  where the pytest proof ran (default TEST_ENVIRONMENT); a drill's is DRILL_ENVIRONMENT.
#   partial      None (every clause shown) or the residual bead that carries the clauses not yet shown.
#   residual     what is not yet shown (required with `partial`).
#   note         anything the counts must not hide (a stand-in, an owner-set target).
#   since_028    required when a case's completeness differs from 028 section 4: which bead and pull request moved it.
# The approval boundary is derived: GATE-STAGING for a full case, or the earliest boundary the residual bead blocks
# (RESIDUAL_BOUNDARIES, from 029 section 13.1) for a partial one.
PROOF_TYPES = ("pytest", "drill", "inspected", "canary", "walkthrough")
TEST_ENVIRONMENT = "test containers (CI and scripts/test.sh)"
DRILL_ENVIRONMENT = "staging stack on the dev box"
# The drill scripts: the commit whose 026 section 16 record holds the drill's result, and that record.
DRILLS = {
    "scripts/staging_check.sh": {"revision": "a5a19fd", "record": "026 section 16, 6B.11 part 1 (PR #75); the dark deploy at 2cb12cf (PR #79)"},
    "scripts/deploy_drill.sh": {"revision": "74cbb53", "record": "026 section 16, 6B.10 (PR #73); batch 2 at main (PRs #82 to #85)"},
    "scripts/alert_drill.sh": {"revision": "ae10624", "record": "026 section 16, 6B.12 (PR #77)"},
    "scripts/restore_drill.sh": {"revision": "472789c", "record": "026 section 16, 6B.13 (PR #78)"},
    "scripts/cutover_rehearsal.sh": {"revision": "2cb12cf", "record": "026 section 16, 6B.11 part 3 (PR #79)"},
}
RESIDUAL_BOUNDARIES = {  # the earliest boundary each residual bead blocks (029 section 13.1)
    "9kg.25": "real-data storage",
    "9kg.27": "the provider canaries (9kg.31.1 to .3)",
    "9kg.28": "the dark deploy (9kg.31.5)",
    "9kg.39": "enabling fetching",
    "9kg.31.5": "the go/no-go (9kg.31.6)",
    "9kg.63": "release preparation (9kg.31.4)",
}
REVISION = re.compile(r"^([0-9a-f]{7,40}|[0-9]{8,})$")  # a commit, or a workflow run id
STAGING_CHECK, DEPLOY_DRILL, ALERT_DRILL, RESTORE_DRILL, CUTOVER = (
    ("drill", "scripts/staging_check.sh"), ("drill", "scripts/deploy_drill.sh"), ("drill", "scripts/alert_drill.sh"),
    ("drill", "scripts/restore_drill.sh"), ("drill", "scripts/cutover_rehearsal.sh"))
ATTESTATION_RUN = ("inspected", "image run 39780920293 on main: build, content check, SBOM, scan and attestation",
                   "178da42", "028 section 4; GitHub Actions run 39780920293")
BUZZ_DELIVERY = ("canary", "one real delivery read back from Buzz", "ae10624", "026 section 16, 6B.12 (PR #77)")
P6_EVIDENCE = {
    "TEST-P6-01": {"proofs": ["pytest", STAGING_CHECK, ATTESTATION_RUN], "partial": "9kg.28",
                   "residual": "verifying the attestation on the host with the force-command"},
    "TEST-P6-02": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-03": {"proofs": ["pytest"]},
    "TEST-P6-04": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-05": {"proofs": ["pytest", STAGING_CHECK, DEPLOY_DRILL]},
    "TEST-P6-06": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-07": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-08": {"proofs": [DEPLOY_DRILL, "pytest"], "pytest": "shape"},
    "TEST-P6-09": {"proofs": ["pytest", DEPLOY_DRILL]},
    "TEST-P6-10": {"proofs": ["pytest", DEPLOY_DRILL],
                   "since_028": "9kg.37 (PR #84): the receipt is a gate; a mismatch refuses the deploy, drilled 60 of 60"},
    "TEST-P6-11": {"proofs": ["pytest", STAGING_CHECK], "partial": "9kg.28", "residual": "tmpfs for the secret files on the host"},
    "TEST-P6-12": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-13": {"proofs": ["pytest", STAGING_CHECK], "partial": "9kg.27",
                   "residual": "the webhook secret, mounted only at the pilot"},
    "TEST-P6-14": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-15": {"proofs": ["pytest", STAGING_CHECK], "partial": "9kg.28", "residual": "the named-device network restriction"},
    "TEST-P6-16": {"proofs": ["pytest", STAGING_CHECK], "partial": "9kg.27",
                   "residual": "live enabled refusals, size and source limits"},
    "TEST-P6-17": {"proofs": ["pytest", ALERT_DRILL]},
    "TEST-P6-18": {"partial": "9kg.27", "residual": "live, once staging has inbound mail (the pilot)"},
    "TEST-P6-19": {"proofs": ["pytest", ALERT_DRILL], "partial": "9kg.27", "residual": "the uncertain send and custody states live"},
    "TEST-P6-20": {"proofs": ["pytest", ALERT_DRILL]},
    "TEST-P6-21": {"proofs": ["pytest", RESTORE_DRILL], "partial": "9kg.28", "residual": "the failed run's alert from the scheduled job"},
    "TEST-P6-22": {"proofs": ["pytest", RESTORE_DRILL], "note": "times measured; the owner sets the RPO and RTO targets"},
    "TEST-P6-23": {"proofs": ["pytest", RESTORE_DRILL]},
    "TEST-P6-24": {"proofs": [DEPLOY_DRILL, "pytest"], "pytest": "shape",
                   "since_028": "9kg.37 (PR #84): a stale backup receipt and another deploy's backup are refused, drilled"},
    "TEST-P6-25": {"proofs": [RESTORE_DRILL, DEPLOY_DRILL, "pytest"], "pytest": "shape", "partial": "9kg.63",
                   "residual": "the deploy drill's data-kept check in the N+1 block fails under the invitation-only intake "
                               "default since PR #85 (59 of 60 on 2026-10-23); the drill must issue an invitation before "
                               "each submission and be re-run green; 9kg.38 (PR #84) drilled the N+1 expand reverted to N on "
                               "the expanded schema and a contract revert refused, 60 of 60, before PR #85 changed the default"},
    "TEST-P6-26": {"proofs": [CUTOVER, "pytest"], "pytest": "shape",
                   "environment": "a stand-in Learn site beside the staging stack on the dev box",
                   "note": "proven on a stand-in Learn site; the live Learn read awaits its preconditions and the owner's go"},
    "TEST-P6-27": {"proofs": [STAGING_CHECK]},
    "TEST-P6-28": {"proofs": ["pytest", STAGING_CHECK], "partial": "9kg.39",
                   "residual": "the fetcher's proxy admits any public name, so production hosts are not denied by name"},
    "TEST-P6-29": {"proofs": ["pytest", RESTORE_DRILL], "partial": "9kg.25", "residual": "erasure replay after a restore"},
    "TEST-P6-30": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-31": {"proofs": ["pytest", STAGING_CHECK], "pytest": "shape", "partial": "9kg.28",
                   "residual": "the deploy force-command on the host"},
    "TEST-P6-32": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-33": {"proofs": ["pytest", STAGING_CHECK]},
    "TEST-P6-34": {"partial": "9kg.27", "residual": "live, with the webhook mounted at the pilot"},
    "TEST-P6-35": {"proofs": ["pytest", RESTORE_DRILL, ALERT_DRILL, DEPLOY_DRILL], "partial": "9kg.31.5",
                   "residual": "the receipt step's scan on a host (9kg.40 built it; CI runs it over the committed evidence, "
                               "the deploy drill ran it on the dev box); not yet wired: restore-drill and scheduled backup "
                               "receipts, alert text (codes only by construction)"},
    "TEST-P6-36": {"partial": "9kg.27",
                   "residual": "the administrator's password and provider tokens (procedures only, 027)"},
    "TEST-P6-37": {"proofs": ["pytest", ATTESTATION_RUN]},
    "TEST-P6-38": {"proofs": ["pytest", ALERT_DRILL, BUZZ_DELIVERY]},
}


class RegisterError(ValueError):
    pass


def gates():
    """The gates in report order: (title, gate, numbered cases, supporting groups). Read at call time, so a probe
    that replaces the module's maps is reported by the same code."""
    return (
        ("first-slice acceptance (005 S1.7)", "GATE-S1", CASES, SUPPORTING),
        ("P2 correspondence acceptance (016 section 7)", "GATE-P2", P2_CASES, {}),
        ("P3 evidence and assessment acceptance (018 section 9)", "GATE-P3", P3_CASES, P3_SUPPORTING),
        ("P4 agreements acceptance (021 section 12)", "GATE-P4", P4_CASES, P4_SUPPORTING),
        ("P5 provisioning acceptance (023 section 9)", "GATE-P5", P5_CASES, P5_SUPPORTING),
        ("P6 staging acceptance (026 section 11; evidence register 9kg.44; live evidence in 026 section 16)",
         "GATE-STAGING", P6_CASES, P6_SUPPORTING),
    )


def groups():
    """Every gated group (numbered cases and supporting groups of every gate) mapped to its tests."""
    merged = {}
    for _, _, cases, supporting in gates():
        merged.update(cases)
        merged.update(supporting)
    return merged


def _proof(case: str, raw, environment: str) -> dict:
    if raw == "pytest":
        return {"type": "pytest", "where": "the gated tests", "environment": environment, "revision": "this run",
                "record": "the per-gate report of this run"}
    kind, where, *rest = raw
    if kind not in PROOF_TYPES:
        raise RegisterError(f"{case}: unknown proof type {kind!r}")
    if kind == "drill":
        if where not in DRILLS:
            raise RegisterError(f"{case}: unknown drill script {where!r}")
        return {"type": kind, "where": where, "environment": DRILL_ENVIRONMENT, **DRILLS[where]}
    if len(rest) != 2 or not REVISION.match(rest[0]) or not rest[1]:
        raise RegisterError(f"{case}: a {kind} proof needs a commit or run id and a record")
    return {"type": kind, "where": where, "environment": "recorded", "revision": rest[0], "record": rest[1]}


def evidence(case: str) -> dict:
    """The register entry for a P6 case, defaults filled only where the register allows them; a missing entry, an
    unknown script or proof type, a partial case without its residual or a residual bead without a boundary raise."""
    if case not in P6_EVIDENCE:
        raise RegisterError(f"{case}: no evidence register entry")
    entry = P6_EVIDENCE[case]
    environment = entry.get("environment", TEST_ENVIRONMENT)
    proofs = [_proof(case, raw, environment) for raw in entry.get("proofs", ["pytest"])]
    if not proofs:
        raise RegisterError(f"{case}: no proofs")
    partial = entry.get("partial")
    if partial and not entry.get("residual"):
        raise RegisterError(f"{case}: partial without a residual")
    if partial and partial not in RESIDUAL_BOUNDARIES:
        raise RegisterError(f"{case}: residual bead {partial} has no boundary in RESIDUAL_BOUNDARIES")
    has_pytest = any(p["type"] == "pytest" for p in proofs)
    return {
        "case": case,
        "proofs": proofs,
        "pytest": entry.get("pytest", "behaviour") if has_pytest else None,
        "completeness": "partial" if partial else "full",
        "partial": partial,
        "residual": entry.get("residual"),
        "boundary": RESIDUAL_BOUNDARIES[partial] if partial else "GATE-STAGING",
        "note": entry.get("note"),
    }


def check_register() -> list[str]:
    """Every problem with the register as data: a case without an entry, an entry without a case, a live-only case
    with a pytest proof or a gated case without one, and whatever evidence() refuses."""
    cases = {*P6_CASES, *P6_LIVE_ONLY}
    problems = [f"{case}: entry without a case" for case in sorted(set(P6_EVIDENCE) - cases)]
    for case in sorted(cases):
        try:
            row = evidence(case)
        except RegisterError as exc:
            problems.append(str(exc))
            continue
        if (row["pytest"] is None) != (case in P6_LIVE_ONLY):
            problems.append(f"{case}: a live-only case has no pytest proof and a gated case has one")
        if row["pytest"] not in (None, "behaviour", "shape"):
            problems.append(f"{case}: pytest must be behaviour or shape")
    return problems


def register(statuses: dict) -> list[dict]:
    """The P6 register rows for one run: each numbered case with this run's gate result (LIVE ONLY for a case with
    no pytest evidence, which is never a pytest result), in case order. A case is proven by this run only when it is
    full, its gate result is PASS and its tests show behaviour, not shape."""
    rows = []
    for case in sorted({*P6_CASES, *P6_LIVE_ONLY}):
        row = evidence(case)
        row["result"] = "LIVE ONLY" if case in P6_LIVE_ONLY else statuses.get(case, "NOT RUN")
        row["proven_this_run"] = row["completeness"] == "full" and row["result"] == "PASS" and row["pytest"] == "behaviour"
        rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    """What the counts must say apart from PASS: full and partial cases, how many this run proved, the live-only
    and shape-only cases, and the residual beads with their cases."""
    residual = {}
    for row in rows:
        if row["partial"]:
            residual.setdefault(row["partial"], []).append(row["case"])
    return {
        "full": sum(r["completeness"] == "full" for r in rows),
        "partial": sum(r["completeness"] == "partial" for r in rows),
        "proven_this_run": sum(r["proven_this_run"] for r in rows),
        "live_only": [r["case"] for r in rows if r["result"] == "LIVE ONLY"],
        "shape_only": [r["case"] for r in rows if r["pytest"] == "shape"],
        "residual": residual,
    }

def key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name' (the function: every instance)."""
    return instance_key(nodeid).split("[", 1)[0]


def instance_key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name[param]' (one instance)."""
    path, _, name = nodeid.partition("::")
    return f"{path.rsplit('/', 1)[-1].removesuffix('.py')}::{name}"
