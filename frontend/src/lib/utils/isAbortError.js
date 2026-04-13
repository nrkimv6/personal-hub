/**
 * Returns true when the value is a fetch AbortError.
 *
 * Shared between the API client and components so abort handling stays consistent.
 */
export function isAbortError(error) {
	return error instanceof Error && error.name === 'AbortError';
}
