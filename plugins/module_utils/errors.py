from ansible.errors import AnsibleError


class AnsibleMatrixError(AnsibleError):
    """ Matrix run-time error. """
    def __init__(self, message=""):
        super(AnsibleMatrixError, self).__init__(message=message)

    def __str__(self):
        return self.message

# class AnsibleMatrixRequestError(MatrixError):
#     def __init__(self):
