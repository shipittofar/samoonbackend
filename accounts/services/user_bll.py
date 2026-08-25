from accounts.models import User
from accounts.selectors import UserDataAccessLayer
from core.exceptions.account import UserNotFoundException

user_dal = UserDataAccessLayer()


class UserBusinessLogicLayer:

    @staticmethod
    def list_users():
        return user_dal.list_all()

    @staticmethod
    def get_user(user_id) -> User:
        user = user_dal.get_by_id(user_id)
        if user is None:
            raise UserNotFoundException()
        return user