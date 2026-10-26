import { useEffect, useState } from 'react'

// 모바일 키보드는 일부 브라우저에서 CSS dvh를 바꾸지 않는다.
export function useViewportHeight() {
  const readHeight = () => Math.round(window.visualViewport?.height ?? window.innerHeight)
  const [height, setHeight] = useState(readHeight)
  useEffect(() => {
    const update = () => setHeight(readHeight())
    window.addEventListener('resize', update)
    window.visualViewport?.addEventListener('resize', update)
    return () => {
      window.removeEventListener('resize', update)
      window.visualViewport?.removeEventListener('resize', update)
    }
  }, [])
  return height
}
