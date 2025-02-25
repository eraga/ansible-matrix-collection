from ansible.errors import AnsibleError


class AnsibleMatrixError(AnsibleError):
    """ Matrix run-time error. """

    def __init__(self, message=""):
        super(AnsibleMatrixError, self).__init__(message=message)

    def __str__(self):
        return self.message


class AnsibleMatrixWarning(AnsibleError):
    def __init__(self, message="", orig_exc=None):
        super(AnsibleMatrixWarning, self).__init__(message=message, orig_exc=orig_exc)

    def __str__(self):
        return self.message

# class AnsibleMatrixRequestError(MatrixError):
#     def __init__(self):
