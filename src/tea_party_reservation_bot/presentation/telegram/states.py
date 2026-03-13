from aiogram.fsm.state import State, StatesGroup


class AdminDraftStates(StatesGroup):
    waiting_for_single_input = State()
    waiting_for_batch_input = State()
    waiting_for_publish_confirmation = State()
