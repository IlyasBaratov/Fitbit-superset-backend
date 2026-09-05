class APIError(Exception):
    def __init__(self, code, message, status=503):
        self.code, self.message, self.status = code, message, status
