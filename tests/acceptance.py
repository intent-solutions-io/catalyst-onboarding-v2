"""The first-slice acceptance plan (005 S1.7, GATE-S1) and the P2 correspondence plan (016 section 7, GATE-P2),
each mapped to the tests that prove each case (S1-T8; P2 task 2C).

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
    ],
    "TEST-P2-07": [
        "test_inbound::test_p2_07_46_a_uidvalidity_change_resyncs_with_no_new_effect_even_mid_batch",
    ],
    "TEST-P2-08": [
        "test_processing::test_d3_d4_staff_decide_only_a_persons_trusted_reply_and_need_every_outcome",
        "test_processing::test_p2_08_09_staff_confirm_each_outcome_and_a_reply_never_satisfies_by_itself",
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


def key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name' (the function: every instance)."""
    return instance_key(nodeid).split("[", 1)[0]


def instance_key(nodeid: str) -> str:
    """'tests/test_x.py::test_name[param]' -> 'test_x::test_name[param]' (one instance)."""
    path, _, name = nodeid.partition("::")
    return f"{path.rsplit('/', 1)[-1].removesuffix('.py')}::{name}"
