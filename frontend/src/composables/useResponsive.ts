import { ref, onMounted, onUnmounted } from 'vue'

const MOBILE_MAX = 768
const TABLET_MAX = 1024

function _read(w: Window) {
  const vw = w.innerWidth
  const vh = w.innerHeight
  return {
    isMobile: vw <= MOBILE_MAX,
    isTablet: vw > MOBILE_MAX && vw <= TABLET_MAX,
    isDesktop: vw > TABLET_MAX,
    isLandscape: vw > vh,
    vw,
    vh,
  }
}

export function useResponsive() {
  const w = window
  const s = _read(w)

  const isMobile = ref(s.isMobile)
  const isTablet = ref(s.isTablet)
  const isDesktop = ref(s.isDesktop)
  const isLandscape = ref(s.isLandscape)
  const width = ref(s.vw)
  const height = ref(s.vh)

  const update = () => {
    const s = _read(w)
    isMobile.value = s.isMobile
    isTablet.value = s.isTablet
    isDesktop.value = s.isDesktop
    isLandscape.value = s.isLandscape
    width.value = s.vw
    height.value = s.vh
  }

  let mql: MediaQueryList | null = null
  const _mqlHandler = () => update()

  onMounted(() => {
    update()
    mql = w.matchMedia(`(max-width: ${MOBILE_MAX}px)`)
    if (mql.addEventListener) {
      mql.addEventListener('change', _mqlHandler)
    } else {
      // 兼容旧浏览器
      ;(mql as any).addListener(_mqlHandler)
    }
    w.addEventListener('resize', update)
    w.addEventListener('orientationchange', update)
  })

  onUnmounted(() => {
    if (mql) {
      if (mql.removeEventListener) {
        mql.removeEventListener('change', _mqlHandler)
      } else {
        ;(mql as any).removeListener(_mqlHandler)
      }
    }
    w.removeEventListener('resize', update)
    w.removeEventListener('orientationchange', update)
  })

  return { isMobile, isTablet, isDesktop, isLandscape, width, height }
}

export { MOBILE_MAX, TABLET_MAX }
