import os
import re
from datetime import datetime
from typing import List

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from sqlalchemy import Column, Integer, TIMESTAMP, VARCHAR, DATE
from sqlalchemy import create_engine, select, extract
from sqlalchemy.orm import Session
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
API_TOKEN = os.environ.get('TG_TOKEN')

engine = create_engine(DATABASE_URL)
Base = declarative_base()


class UserModel(Base):
    __tablename__ = 'users'
    id = Column(Integer, nullable=False, unique=True, primary_key=True, autoincrement=True)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.now())
    updated_at = Column(TIMESTAMP, nullable=False, default=datetime.now(), onupdate=datetime.now())
    name = Column(VARCHAR(255), nullable=False, unique=True)
    birthdate = Column(DATE, nullable=False)


Base.metadata.create_all(engine)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
session = Session(bind=engine)


def get_age_letter(age: int) -> str:
    digit = age % 10
    if digit == 0 or digit > 4 or (10 <= age <= 14):
        return "лет"
    elif digit == 1:
        return "год"
    else:
        return "года"


def get_age(birthdate: datetime) -> int:
    today = datetime.now()
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    return age


def get_age_message(age: int) -> str:
    if age < 1:
        return "Ты только родился! Добро пожаловать в этот беспощадный Мир!"
    elif age < 7:
        return "Тебе {0} {1}. Не шали в садике!".format(age, get_age_letter(age))
    elif age < 18:
        return "Тебе {0} {1}. Не забудь про уроки!".format(age, get_age_letter(age))
    elif age < 23:
        return "Тебе {0} {1}. Сессия не за горами!".format(age, get_age_letter(age))
    elif age < 65:
        return "Тебе {0} {1}. На работу не опоздай!".format(age, get_age_letter(age))
    else:
        return "Тебе {0} {1}. На пенсии конечно хорошо, но следи за собой!".format(age, get_age_letter(age))


def get_birthday_users(birthdate: datetime) -> List[str]:
    month = birthdate.month
    day = birthdate.day
    try:
        stmt = select(UserModel).where(extract('month', UserModel.birthdate) == month,
                                       extract('day', UserModel.birthdate) == day)
        result: List[str] = [user.name for user in session.scalars(stmt)]
        return result
    except Exception as ex:
        raise ex


def update_user(name: str, birthday: datetime) -> None:
    try:
        stmt = select(UserModel).where(UserModel.name.ilike(name))
        if session.scalars(stmt).first() is not None:
            raise Exception("Пользователь {0} уже зарегистрирован.".format(name))
        user = UserModel()
        user.birthdate = birthday
        user.name = name
        session.add(user)
        session.commit()
    except Exception as ex:
        raise ex


# States
class Form(StatesGroup):
    name = State()
    birthday = State()


@dp.message_handler(commands=['start', 'help'])
async def start_handler(message: types.Message) -> None:
    await message.reply("/start print this help \n"
                        "/remind_birthday enter your name and birthday \n"
                        "/birthdays_today {date} show people whose birthday is date or today default \n"
                        "/people show all registered people \n"
                        "/cancel cancel input")


@dp.message_handler(state='*', commands=['cancel'])
async def cancel_handler(message: types.Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        return

    await state.finish()
    await message.reply('Ввод прекращен. Начинаем сначала')


@dp.message_handler(commands=['remind_birthday'])
async def start_handler(message: types.Message) -> None:
    await Form.name.set()
    await message.reply("Привет! Как тебя зовут?")


@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext) -> None:
    check = re.match('^[a-zA-Zа-яА-Я]+$', message.text)
    if check is None:
        await message.reply("У тебя цифро-символьное имя? Не верю! Повтори ввод!")
        return
    async with state.proxy() as data:
        data['name'] = message.text
    await Form.next()
    await message.reply("{0}, когда ты родился?".format(data['name']))


@dp.message_handler(state=Form.birthday)
async def process_birthday(message: types.Message, state: FSMContext) -> None:
    try:
        birthday = datetime.strptime(message.text, '%d.%m.%Y')
    except:
        await message.reply("Дата должна быть в формате dd.MM.YYYY. Введи еще раз")
        return

    age = get_age(birthday)
    if age < 0:
        await message.reply("Ты терминатор из будущего? Не верю! Когда же ты родился?")
        return
    else:
        user = UserModel()
        async with state.proxy() as data:
            data['birthdate'] = birthday
            user.birthdate = birthday
            user.name = data['name']
        try:
            update_user(data['name'], data['birthdate'])
            await message.reply(get_age_message(age))
            await Form.next()
        except Exception as ex:
            await message.reply(
                "Увы, что-то пошло не так: {0}. \nПовтори ввод или через /cancel сделай по новому".format(ex))


@dp.message_handler(commands=['people'])
async def show_registered_people(message: types.Message) -> None:
    try:
        stmt = select(UserModel).order_by(UserModel.created_at)
        msg: str = "Зарегистрированные пользователи:"
        for user in session.scalars(stmt):
            msg += "\n{0}\t{1}\t{2}".format(user.created_at, user.name, user.birthdate)
        await message.reply(msg)
    except Exception as ex:
        raise ex


@dp.message_handler(commands=['birthdays_today'])
async def process_birthdays_today(message: types.Message) -> None:
    tokens = message.text.split(" ")
    date = datetime.now().date()
    if len(tokens) > 1:
        try:
            date = datetime.strptime(tokens[1], '%d.%m.%Y')
        except Exception as ex:
            ...

    users: List[str] = get_birthday_users(date)
    if len(users) > 0:
        msg: str = "Именинники на {0}:\n".format(date.strftime("%d.%m.%Y"))
        for name in users:
            msg += name + '\n'
        await message.reply(msg)
    else:
        await message.reply("Именнинников на {0} нет ".format(date.strftime("%d.%m.%Y")))


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
