from __future__ import annotations

from starlette import status


class AppError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidUploadError(AppError):
    def __init__(self, message: str = "Uploaded file must include a file name."):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)


class UnsupportedFileTypeError(AppError):
    def __init__(self):
        super().__init__(
            "Unsupported file type. Only .pdf and .docx files are allowed.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )


class UnsupportedImageTypeError(AppError):
    def __init__(self):
        super().__init__(
            "Unsupported image type. Only .png, .jpg, and .jpeg files are allowed.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )


class EmptyFileError(AppError):
    def __init__(self):
        super().__init__("Uploaded file is empty.", status.HTTP_400_BAD_REQUEST)


class FileTooLargeError(AppError):
    def __init__(self, max_size_mb: int):
        super().__init__(
            f"File is too large. Maximum allowed size is {max_size_mb}MB.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )


class FileStorageError(AppError):
    def __init__(self):
        super().__init__(
            "Unable to store the uploaded file.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class FigureStorageError(AppError):
    def __init__(self):
        super().__init__(
            "Unable to store the uploaded figure.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ExtractionError(AppError):
    def __init__(self, message: str = "Unable to extract text"):
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY)


class ProjectNotFoundError(AppError):
    def __init__(self, project_id: str):
        super().__init__(
            f"Project '{project_id}' was not found.",
            status.HTTP_404_NOT_FOUND,
        )


class ProjectSectionsUnavailableError(AppError):
    def __init__(self, project_id: str):
        super().__init__(
            f"Project '{project_id}' does not have generated sections to edit yet.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class ProjectExportContentError(AppError):
    def __init__(self, project_id: str):
        super().__init__(
            f"Project '{project_id}' does not have formatted sections available for export.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class EmptyGenerationSourceError(AppError):
    def __init__(self, project_id: str):
        super().__init__(
            f"Project '{project_id}' does not have extracted text to generate from.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class GenerationConfigurationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE)


class GenerationError(AppError):
    def __init__(self, message: str = "Unable to generate structured paper"):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)


class ExportDependencyError(AppError):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE)


class ExportError(AppError):
    def __init__(self, message: str = "Unable to export the project"):
        super().__init__(message, status.HTTP_502_BAD_GATEWAY)


class InvalidAgentResponseError(GenerationError):
    def __init__(self, agent_name: str):
        super().__init__(f"Agent '{agent_name}' returned invalid JSON output.")


class AgentExecutionError(GenerationError):
    def __init__(self, agent_name: str, message: str | None = None):
        detail = message or "Agent processing failed."
        super().__init__(f"Agent '{agent_name}' failed. {detail}")


class MCPToolError(GenerationError):
    def __init__(self, tool_name: str):
        super().__init__(f"MCP tool '{tool_name}' failed.")
