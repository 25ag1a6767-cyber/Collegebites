import { useEffect, useState } from "react";

/**
 * Debounce a rapidly changing value (such as a search input) to prevent
 * per-keystroke API bursts and unnecessary SSE stream reconnects.
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
