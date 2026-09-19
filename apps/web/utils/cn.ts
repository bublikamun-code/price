import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Слияние классов для UI-примитивов (модель shadcn-vue). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
