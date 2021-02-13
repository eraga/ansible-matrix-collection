from ansible.errors import AnsibleError


class MatrixError(AnsibleError):
    """ Matrix run-time error. """
    def __init__(self, message=""):
        super(MatrixError, self).__init__(message=message)

    def __str__(self):
        return self.message

# class AnsibleMatrixRequestError(MatrixError):
#     def __init__(self):
