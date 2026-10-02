"""Local voice commands: apps, calendar, weather, notes, and the iPhone bridge.

Names are parsed from the transcript here, the same way timers parse a duration.
decide() in siri.py calls route_before_api() before any TypeSafe or LLM call.

Nothing in this module listens on a socket. The iPhone bridge only polls an
iCloud Drive folder. App launches, site URLs, and shortcut runs go through
argument lists, never a shell string. A shortcut runs only when the Jev folder
can be verified; `shortcuts list --folder-name` alone is not proof, because a
missing folder makes that command print every shortcut. Message text is
returned as LocalSpeech so the caller can speak it with the macOS say command
and must not send it to Fish or any API. Bank and portal pages are opened in
Chrome only. This module never fetches them and never moves money."""
import subprocess  # re-exported so tests can patch commands.subprocess.run

from .config import (
    FUZZY_CUTOFF,
    APP_FUZZY_CUTOFF,
    APP_INDEX_TTL,
    CONFIRM_SECONDS,
    SHORTCUT_FOLDER,
    SHORTCUT_CACHE_SECONDS,
    SHIFT_TITLE_PATTERNS,
    SHIFT_HORIZON_DAYS,
    SCHOOL_HORIZON_DAYS,
    BILL_HORIZON_DAYS,
    DEFAULT_APPLE_PAY_ANCHOR,
    PRINCESS_SHORTCUT,
    PRINCESS_ACADEMY_URL,
    SHOPIFY_ORDERS_URL,
    BRIGHTNESS_UP_CODE,
    BRIGHTNESS_DOWN_CODE,
    SHOW_DESKTOP_CODE,
    VOLUME_WORDS,
    ZOE_EVENT_RE,
    MY_LOVE_HANDLES,
    MESSAGES_DB,
    JEV_DOCS,
    NOTES_PATH,
    DUE_PATH,
    IHSS_PATH,
    MONEY_PATH,
    DUE_HORIZON_DAYS,
    UPLAND_LAT,
    UPLAND_LON,
    WEATHER_TIMEOUT,
    FOCUS_ON_NAME,
    FOCUS_OFF_NAME,
    FOCUS_DEFAULT_SECONDS,
    CASE_STATUS_URL,
    GMAIL_TOKEN_ACCOUNT,
    BRIDGE_INBOX,
    BRIDGE_OUTBOX,
    BRIDGE_SECRET_ACCOUNT,
    BRIDGE_MAX_AGE,
    BRIDGE_POLL_SECONDS,
    NONCE_LOG,
    NONCE_LIMIT,
    NONCE_RE,
    BRIDGE_ALLOW,
    KNOWN_APPS,
    APP_NICKNAMES,
    SITE_CONFIG,
    FOLDER_PATHS,
    APP_DIRS,
    FINDER_PATH,
    PROTECTED_IDS,
    PROTECTED_NAMES,
    CONFIRM,
    YES_RE,
    NO_RE,
    QUIT_ALL_RE,
    QUIT_ALL_ONLY_RE,
    _OPEN_VERBS,
    _QUIT_VERBS,
    JOINER_RE,
    _PLEASE,
    _TAIL,
    _PLAY,
    STRICT_PATTERNS,
    _NOTE_CMD_RE,
    _IHSS_CMD_RE,
    _BARE_RUN_RE,
    LOCAL_PATTERNS,
    HELP_TEXT,
    SCHOOL_RE,
    BILL_RE,
)

from .textutil import (
    _clean,
    _norm,
    _ordinal,
    _clock,
    _in_how_long,
    _day_phrase,
    _join_names,
    _month_day,
    _spoken_span,
    _hours_phrase,
    _until_day,
    _hours_minutes,
    _weekday_month,
)

from .shell import (
    _run,
)

from .confirm import (
    _PENDING,
    confirmation_pending,
    clear_confirmation,
    arm_confirmation,
    refresh_confirmation,
    confirmation_status,
    take_confirmation,
    isolate_confirmations,
    is_quit_all,
    quit_all_is_compound,
    is_private_message_request,
)

from .apps import (
    _index_cache,
    app_alias_map,
    site_index,
    _drop_my,
    _lookup_app,
    known_app_name,
    resolve_site,
    resolve_folder,
    music_target,
    app_index,
    _display_name,
    resolve_app,
    parse_app_name,
    _appkit,
    running_regular_apps,
    _own_pids,
    _is_self,
    is_protected,
    _running_match,
    _is_running,
    launch_app,
    open_any_app,
    quit_any_app,
    quit_all_apps,
    speak_open_apps,
    app_is_installed,
)

from .time_date import (
    speak_time,
    speak_date,
)

from .calendar_shift import (
    _store,
    _calendar_granted,
    _CAL_MISSING,
    _CAL_DENIED,
    _CAL_FAILED,
    _import_eventkit,
    _event_store,
    _wait_for,
    _request_full_access,
    ensure_calendar_access,
    _nsdate,
    _stamp,
    _title,
    _all_day,
    _cancelled,
    _events_between,
    _calendar_problem,
    _upcoming,
    speak_next_event,
    speak_today_schedule,
    is_shift_title,
    speak_next_shift,
    _calendar_name,
    speak_zoe_tomorrow,
    _plain_event,
    _load_plain_events,
    weekend_bounds,
    _covers_day,
    describe_work_weekend,
    describe_shift_length,
    speak_working_weekend,
    speak_shift_length,
)

from .weather import (
    _WMO,
    _WEATHER_FAIL,
    _weather_phrase,
    speak_weather,
    gmail_brief_line,
    _gmail_stub_noted,
)

from .notes_due import (
    take_note,
    _dated_lines,
    _read_due_lines,
    speak_due,
)

from .money import (
    _semi_period,
    _parse_ihss,
    _period_total,
    log_ihss,
    brea_from_due,
    speak_brea_start,
    _filtered_due,
    _speak_item_list,
    speak_school_due,
    speak_rent,
    speak_bills,
    next_biweekly,
    _month_end,
    next_semi_payday,
    load_pay_schedule,
    speak_payday,
    speak_ihss_period,
    remind_timesheet,
)

from .messages import (
    LocalSpeech,
    _FDA_MESSAGE,
    _is_fda_error,
    decode_attributed_body,
    _typedstream_string,
    _message_body,
    _clip_speech,
    _probe_messages_db,
    _open_messages_db,
    speak_my_love_messages,
)

from .system import (
    speak_help,
    _https_url,
    _open_in_chrome,
    open_site_from_text,
    open_folder_from_text,
    change_brightness,
    show_desktop,
    speak_battery,
    take_screenshot,
    empty_trash,
    continue_chatgpt,
    open_case_status,
)

from .media import (
    play_on_youtube,
    parse_volume_level,
    set_mac_volume,
)

from .shortcuts import (
    _UUID_RE,
    _shortcut_cache,
    run_jev_folder_shortcut,
    begin_focus,
    finish_focus,
    open_princess_academy,
    parse_shortcut_name,
    spoken_shortcut_from,
    clear_shortcut_cache,
    _shortcuts_output,
    _parse_id_line,
    parse_shortcut_ids,
    parse_folder_rows,
    find_jev_folder,
    catalog_from_listings,
    _load_shortcut_catalog,
    jev_shortcut_catalog,
    list_jev_shortcuts,
    resolve_shortcut,
    _ident_for_name,
    _run_catalog_shortcut,
    run_named_shortcut,
)

from .routing import (
    route_before_api,
    preview_action,
    route_open_phrase,
    bare_run_matches_folder,
)

from .bridge import (
    _bridge_thread,
    _bridge_lock,
    _bridge_secret_warned,
    bridge_allowed,
    _canonical_ts,
    _bridge_secret,
    _expected_sig,
    _load_nonces,
    _remember_nonce,
    _nonce_used,
    _write_outbox,
    _delete_inbox,
    _process_bridge_file,
    poll_bridge,
    start_bridge_thread,
)

from .brief import (
    speak_today,
    _count_today_events,
    speak_brief,
)
