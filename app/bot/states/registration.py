from aiogram.fsm.state import State, StatesGroup


class RegistrationSG(StatesGroup):
    confirm_name = State()
    edit_name = State()
    choose_gender = State()
    choose_country = State()
    search_country = State()
