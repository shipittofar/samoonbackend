class BaseAppException(Exception):

    status_code = 400

    code = "application_error"

    message = "Application error"

    def __init__(self, message=None, detail=None):
        resolved = detail if detail is not None else message
        if resolved is not None:
            self.message = resolved

        super().__init__(self.message)