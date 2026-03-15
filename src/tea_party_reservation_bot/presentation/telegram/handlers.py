from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from tea_party_reservation_bot.application.telegram import (
    TelegramBotApplicationService,
    TelegramUserProfile,
)
from tea_party_reservation_bot.domain.events import EventPreview
from tea_party_reservation_bot.domain.rbac import Actor
from tea_party_reservation_bot.exceptions import AuthorizationError, ValidationError
from tea_party_reservation_bot.infrastructure.telegram.deep_links import decode_start_parameter
from tea_party_reservation_bot.infrastructure.telegram.publication import (
    TelegramPublicationRenderer,
)
from tea_party_reservation_bot.presentation.telegram.keyboards import (
    admin_events_keyboard,
    admin_menu_keyboard,
    cancellation_confirm_keyboard,
    draft_preview_keyboard,
    event_actions_keyboard,
    notifications_keyboard,
    registration_cancel_keyboard,
    visitor_menu_keyboard,
)
from tea_party_reservation_bot.presentation.telegram.renderers import (
    render_admin_denied,
    render_admin_events,
    render_admin_preview,
    render_batch_template,
    render_event_card,
    render_event_details,
    render_events_empty,
    render_help,
    render_my_empty,
    render_my_registration,
    render_notifications,
    render_registration_result,
    render_roster,
    render_single_event_template,
    render_unknown_text,
    render_welcome,
)
from tea_party_reservation_bot.presentation.telegram.states import AdminDraftStates

LoadActor = Callable[[User], Awaitable[Actor]]

_INVALID_CALLBACK_TEXT = "Некорректное действие. Попробуйте снова."


@dataclass(slots=True, frozen=True)
class TelegramHandlerDependencies:
    application_service: TelegramBotApplicationService
    publication_renderer: TelegramPublicationRenderer
    bot_username: str


def build_router(deps: TelegramHandlerDependencies) -> Router:
    router = Router(name="telegram")
    router.message.filter(_is_private_message)
    router.callback_query.filter(_is_private_callback)
    load_actor = _build_load_actor(deps)
    _register_public_menu_handlers(router, deps, load_actor)
    _register_public_callback_handlers(router, deps)
    _register_registration_handlers(router, deps, load_actor)
    _register_admin_entry_handlers(router, deps, load_actor)
    _register_admin_draft_handlers(router, deps, load_actor)
    _register_admin_event_handlers(router, deps, load_actor)
    _register_misc_handlers(router)
    return router


def _build_load_actor(deps: TelegramHandlerDependencies) -> LoadActor:
    async def load_actor(message_user: User) -> Actor:
        profile = TelegramUserProfile(
            telegram_user_id=message_user.id,
            username=message_user.username,
            first_name=message_user.first_name,
            last_name=message_user.last_name,
        )
        return await deps.application_service.sync_profile(profile)

    return load_actor


def _is_private_message(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def _is_private_callback(callback: CallbackQuery) -> bool:
    return isinstance(callback.message, Message) and callback.message.chat.type == ChatType.PRIVATE


def _render_preview(deps: TelegramHandlerDependencies, previews: list[EventPreview]) -> str:
    if len(previews) == 1:
        payload = deps.publication_renderer.render_single_event_post(
            bot_username=deps.bot_username,
            preview=previews[0],
            event_id="preview-event",
        )
    else:
        payload = deps.publication_renderer.render_batch_post(
            bot_username=deps.bot_username,
            previews=previews,
            event_ids=[f"preview-{index}" for index, _ in enumerate(previews, start=1)],
        )
    return render_admin_preview(previews, payload)


def _extract_callback_suffix(data: str | None, prefix: str) -> str | None:
    if data is None or not data.startswith(prefix):
        return None
    suffix = data.removeprefix(prefix)
    return suffix or None


def _register_public_menu_handlers(
    router: Router,
    deps: TelegramHandlerDependencies,
    load_actor: LoadActor,
) -> None:
    async def send_events(message: Message) -> None:
        events = await deps.application_service.list_events()
        if not events:
            await message.answer(render_events_empty())
            return
        await message.answer("Ближайшие дегустации:")
        for event in events:
            await message.answer(
                render_event_card(event), reply_markup=event_actions_keyboard(event)
            )

    async def send_my_registrations(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        registrations = await deps.application_service.list_my_registrations(
            telegram_user_id=user.id
        )
        if not registrations:
            await message.answer(render_my_empty())
            return
        for registration in registrations:
            keyboard = (
                registration_cancel_keyboard(registration) if registration.can_cancel else None
            )
            await message.answer(render_my_registration(registration), reply_markup=keyboard)

    async def send_notifications(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        settings = await deps.application_service.get_notifications(telegram_user_id=user.id)
        await message.answer(
            render_notifications(settings),
            reply_markup=notifications_keyboard(settings.enabled),
        )

    @router.message(CommandStart())
    async def start(message: Message, command: CommandObject | None) -> None:
        user = message.from_user
        if user is None:
            return
        await load_actor(user)
        await message.answer(render_welcome(), reply_markup=visitor_menu_keyboard())
        if command is None or not command.args:
            return
        start_context = decode_start_parameter(command.args)
        if not start_context.has_event:
            return
        event = await deps.application_service.get_event(start_context.event_id or "")
        if event is None:
            await message.answer("Событие не найдено или уже недоступно.")
            return
        await message.answer(
            render_event_details(event), reply_markup=event_actions_keyboard(event)
        )

    @router.message(Command("events"))
    @router.message(F.text == "Ближайшие дегустации")
    async def events(message: Message) -> None:
        user = message.from_user
        if user is not None:
            await load_actor(user)
        await send_events(message)

    @router.message(Command("my"))
    @router.message(F.text == "Мои записи")
    async def my_registrations(message: Message) -> None:
        user = message.from_user
        if user is not None:
            await load_actor(user)
        await send_my_registrations(message)

    @router.message(Command("help"))
    @router.message(F.text == "Как это работает")
    async def help_command(message: Message) -> None:
        await message.answer(render_help())

    @router.message(F.text == "Уведомления")
    async def notifications(message: Message) -> None:
        user = message.from_user
        if user is not None:
            await load_actor(user)
        await send_notifications(message)


def _register_public_callback_handlers(router: Router, deps: TelegramHandlerDependencies) -> None:
    @router.callback_query(F.data == "notifications:toggle")
    async def toggle_notifications(callback: CallbackQuery) -> None:
        user = callback.from_user
        settings = await deps.application_service.toggle_notifications(telegram_user_id=user.id)
        if isinstance(callback.message, Message):
            message = cast(Message, callback.message)
            await message.edit_text(
                render_notifications(settings),
                reply_markup=notifications_keyboard(settings.enabled),
            )
        await callback.answer("Готово")

    @router.callback_query(F.data.startswith("event:detail:"))
    async def event_details(callback: CallbackQuery) -> None:
        event_id = _extract_callback_suffix(callback.data, "event:detail:")
        if event_id is None:
            await callback.answer(_INVALID_CALLBACK_TEXT, show_alert=True)
            return
        event = await deps.application_service.get_event(event_id)
        if isinstance(callback.message, Message):
            message = cast(Message, callback.message)
            if event is None:
                await callback.answer("Событие не найдено или уже недоступно.", show_alert=True)
                return
            else:
                await message.edit_text(
                    render_event_details(event),
                    reply_markup=event_actions_keyboard(event),
                )
        await callback.answer()


def _register_registration_handlers(
    router: Router,
    deps: TelegramHandlerDependencies,
    load_actor: LoadActor,
) -> None:
    @router.callback_query(F.data.startswith("event:register:"))
    async def register_for_event(callback: CallbackQuery) -> None:
        event_id = _extract_callback_suffix(callback.data, "event:register:")
        if event_id is None:
            await callback.answer(_INVALID_CALLBACK_TEXT, show_alert=True)
            return
        try:
            result = await deps.application_service.register_for_event(
                telegram_user_id=callback.from_user.id,
                event_id=event_id,
                idempotency_key=f"callback:{callback.id}:{event_id}",
            )
        except LookupError:
            if callback.message is not None:
                await callback.message.answer("Событие не найдено или уже недоступно.")
            await callback.answer()
            return
        if callback.message is not None:
            await callback.message.answer(render_registration_result(result))
        await callback.answer("Готово")

    @router.callback_query(F.data == "noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data.startswith("my:cancel_prompt:"))
    async def prompt_cancel_registration(callback: CallbackQuery) -> None:
        registration_id = _extract_callback_suffix(callback.data, "my:cancel_prompt:")
        if registration_id is None:
            await callback.answer(_INVALID_CALLBACK_TEXT, show_alert=True)
            return
        if isinstance(callback.message, Message):
            message = cast(Message, callback.message)
            await message.edit_reply_markup(
                reply_markup=cancellation_confirm_keyboard(registration_id)
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("my:cancel_yes:"))
    async def confirm_cancel_registration(callback: CallbackQuery) -> None:
        registration_id = _extract_callback_suffix(callback.data, "my:cancel_yes:")
        if registration_id is None:
            await callback.answer(_INVALID_CALLBACK_TEXT, show_alert=True)
            return
        cancelled = await deps.application_service.cancel_registration(
            telegram_user_id=callback.from_user.id,
            registration_id=registration_id,
            idempotency_key=f"callback:{callback.id}:{registration_id}",
        )
        if callback.message is not None:
            text = "Запись отменена." if cancelled else "Отменить запись уже нельзя."
            await callback.message.answer(text)
        await callback.answer("Готово")

    @router.callback_query(F.data.startswith("my:cancel_no:"))
    async def abort_cancel_registration(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.answer("Запись оставлена без изменений.")
        await callback.answer("Готово")

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Текущее действие отменено.")


def _register_admin_entry_handlers(
    router: Router,
    deps: TelegramHandlerDependencies,
    load_actor: LoadActor,
) -> None:
    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        actor = await load_actor(user)
        try:
            deps.application_service.ensure_admin(actor)
        except AuthorizationError:
            await message.answer(render_admin_denied(), reply_markup=visitor_menu_keyboard())
            return
        await message.answer("Раздел администратора.", reply_markup=admin_menu_keyboard())

    @router.message(Command("new_event"))
    @router.message(F.text == "Создать событие")
    async def new_event(message: Message, state: FSMContext) -> None:
        user = message.from_user
        if user is None:
            return
        actor = await load_actor(user)
        try:
            deps.application_service.ensure_admin(actor)
        except AuthorizationError:
            await message.answer(render_admin_denied(), reply_markup=visitor_menu_keyboard())
            return
        await state.set_state(AdminDraftStates.waiting_for_single_input)
        await state.update_data(mode="single")
        await message.answer(render_single_event_template())

    @router.message(Command("new_batch"))
    @router.message(F.text == "Создать неделю")
    async def new_batch(message: Message, state: FSMContext) -> None:
        user = message.from_user
        if user is None:
            return
        actor = await load_actor(user)
        try:
            deps.application_service.ensure_admin(actor)
        except AuthorizationError:
            await message.answer(render_admin_denied(), reply_markup=visitor_menu_keyboard())
            return
        await state.set_state(AdminDraftStates.waiting_for_batch_input)
        await state.update_data(mode="batch")
        await message.answer(render_batch_template())


def _register_admin_draft_handlers(
    router: Router,
    deps: TelegramHandlerDependencies,
    load_actor: LoadActor,
) -> None:
    @router.message(AdminDraftStates.waiting_for_single_input)
    @router.message(AdminDraftStates.waiting_for_batch_input)
    async def collect_admin_draft(message: Message, state: FSMContext) -> None:
        user = message.from_user
        text = message.text
        if user is None or text is None:
            return
        actor = await load_actor(user)
        data = await state.get_data()
        mode = str(data.get("mode", "single"))
        try:
            previews = list(
                deps.application_service.preview_batch(actor, text)
                if mode == "batch"
                else [deps.application_service.preview_single_event(actor, text)]
            )
        except (AuthorizationError, ValidationError) as exc:
            await message.answer(str(exc))
            return
        await state.set_state(AdminDraftStates.waiting_for_publish_confirmation)
        await state.update_data(raw_text=text, mode=mode)
        await message.answer(_render_preview(deps, previews), reply_markup=draft_preview_keyboard())

    @router.callback_query(
        AdminDraftStates.waiting_for_publish_confirmation, F.data == "draft:edit"
    )
    async def edit_draft(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        mode = str(data.get("mode", "single"))
        next_state = (
            AdminDraftStates.waiting_for_batch_input
            if mode == "batch"
            else AdminDraftStates.waiting_for_single_input
        )
        await state.set_state(next_state)
        if callback.message is not None:
            await callback.message.answer("Отправьте исправленный текст.")
        await callback.answer("Исправление")

    @router.callback_query(
        AdminDraftStates.waiting_for_publish_confirmation, F.data == "draft:cancel"
    )
    async def cancel_draft(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        if callback.message is not None:
            await callback.message.answer("Черновик отменен.")
        await callback.answer("Отменено")

    @router.callback_query(
        AdminDraftStates.waiting_for_publish_confirmation, F.data == "draft:publish"
    )
    async def publish_draft(callback: CallbackQuery, state: FSMContext) -> None:
        user = callback.from_user
        data = await state.get_data()
        raw_text = data.get("raw_text")
        mode = str(data.get("mode", "single"))
        if not isinstance(raw_text, str):
            await state.clear()
            await callback.answer("Черновик потерян", show_alert=True)
            return
        actor = await load_actor(user)
        try:
            receipt = (
                await deps.application_service.publish_batch_events(
                    actor=actor,
                    raw_text=raw_text,
                    idempotency_key=f"callback:{callback.id}:draft:batch",
                )
                if mode == "batch"
                else await deps.application_service.publish_single_event(
                    actor=actor,
                    raw_text=raw_text,
                    idempotency_key=f"callback:{callback.id}:draft:single",
                )
            )
        except (AuthorizationError, ValidationError) as exc:
            if callback.message is not None:
                await callback.message.answer(str(exc))
            await callback.answer("Ошибка", show_alert=True)
            return
        await state.clear()
        if callback.message is not None:
            await callback.message.answer(receipt.message)
        await callback.answer("Готово")


def _register_admin_event_handlers(
    router: Router,
    deps: TelegramHandlerDependencies,
    load_actor: LoadActor,
) -> None:
    @router.message(Command("events_admin"))
    @router.message(Command("participants"))
    @router.message(F.text == "События")
    @router.message(F.text == "Участники")
    async def admin_events(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        actor = await load_actor(user)
        try:
            events = list(await deps.application_service.list_admin_events(actor))
        except AuthorizationError:
            await message.answer(render_admin_denied(), reply_markup=visitor_menu_keyboard())
            return
        await message.answer(
            render_admin_events(events), reply_markup=admin_events_keyboard(events)
        )

    @router.callback_query(F.data.startswith("admin:roster:"))
    async def admin_roster(callback: CallbackQuery) -> None:
        event_id = _extract_callback_suffix(callback.data, "admin:roster:")
        if event_id is None:
            await callback.answer(_INVALID_CALLBACK_TEXT, show_alert=True)
            return
        actor = await load_actor(callback.from_user)
        try:
            roster = await deps.application_service.get_event_roster(actor=actor, event_id=event_id)
        except AuthorizationError:
            if callback.message is not None:
                await callback.message.answer(render_admin_denied())
            await callback.answer()
            return
        if callback.message is not None:
            await callback.message.answer(
                render_roster(roster)
                if roster is not None
                else "Список участников пока недоступен."
            )
        await callback.answer()


def _register_misc_handlers(router: Router) -> None:
    @router.message()
    async def fallback(message: Message) -> None:
        await message.answer(render_unknown_text())
