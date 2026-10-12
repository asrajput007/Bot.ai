from .errors import AccessDeniedError, UnknownOperatorError


class AccessPolicy:
    def __init__(self, operators, access_map, directory):
        self._operators = list(operators)
        self._access = {name: list(values) for name, values in access_map.items()}
        self._directory = directory

    def operators(self):
        return list(self._operators)

    def validate_user(self, user):
        if user not in self._operators:
            raise UnknownOperatorError(f"Unknown operator: {user!r}")

    def can(self, user, client_id):
        if user not in self._operators:
            return False
        if not self._access:
            return True
        granted = self._access.get(user, [])
        if "*" in granted or client_id in granted:
            return True
        return self._directory.created_by(client_id) == user

    def require(self, user, client_id):
        self.validate_user(user)
        if not self.can(user, client_id):
            raise AccessDeniedError(f"{user} does not have access to this client workspace.")

    def client_ids(self, user):
        self.validate_user(user)
        return [client.id for client in self._directory.all() if self.can(user, client.id)]

    def matrix(self):
        ids = [client.id for client in self._directory.all()]
        return {user: [cid for cid in ids if self.can(user, cid)] for user in self._operators}
