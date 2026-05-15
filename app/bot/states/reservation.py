from aiogram.fsm.state import State, StatesGroup


class ReservationSG(StatesGroup):
    choose_date = State()
    choose_slot = State()
    confirm = State()


class ProfileSG(StatesGroup):
    choose_field = State()
    edit_name = State()
    choose_gender = State()
    choose_country = State()
    search_country = State()
