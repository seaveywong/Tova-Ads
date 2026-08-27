// 请求序列守卫：快速连续触发加载时，只让最后一次的结果生效（旧响应后到被丢弃）。
// 用法：
//   const guard = useLatest()
//   const load = async () => {
//     const my = guard.next()
//     const r = await GET(...)
//     if (!my()) return      // 不是最新请求——丢弃
//     data.value = r
//   }
export function useLatest() {
  let seq = 0
  return {
    next() { const my = ++seq; return () => my === seq },
  }
}
