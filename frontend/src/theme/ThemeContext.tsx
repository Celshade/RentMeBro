import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

/** A user-chosen theme, or `system` to follow the OS preference. */
export type Theme = 'light' | 'dark' | 'system';

/**
 * @property theme - The user's chosen theme.
 * @property setTheme - Updates the chosen theme and persists it.
 */
interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const THEME_STORAGE_KEY = 'rentmebro_theme';


/**
 * Provides manual light/dark theme state to the app, stamping
 * `data-theme` on the document root so `index.css` can override the
 * OS-driven `prefers-color-scheme` palette.
 * @param props.children - The subtree that can call useTheme().
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  });

  useEffect(() => {
    if (theme === 'system') {
      document.documentElement.removeAttribute('data-theme');
      localStorage.removeItem(THEME_STORAGE_KEY);
    } else {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
  }, [theme]);

  const value = { theme, setTheme };
  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}


/** @returns The current theme context; throws outside a ThemeProvider. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
