<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const canvasRef = ref<HTMLCanvasElement>()
let frame = 0
let resizeObserver: ResizeObserver | null = null

type Particle = { x: number; y: number; vx: number; vy: number; radius: number; alpha: number }
const particles: Particle[] = []

function seed(width: number, height: number) {
  particles.length = 0
  const count = Math.max(18, Math.min(42, Math.round((width * height) / 42000)))
  for (let i = 0; i < count; i += 1) {
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.08,
      vy: -0.025 - Math.random() * 0.055,
      radius: 0.6 + Math.random() * 1.8,
      alpha: 0.08 + Math.random() * 0.18,
    })
  }
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.getBoundingClientRect()
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(rect.width * dpr)
  canvas.height = Math.round(rect.height * dpr)
  const context = canvas.getContext('2d')
  context?.setTransform(dpr, 0, 0, dpr, 0, 0)
  seed(rect.width, rect.height)
}

function draw() {
  const canvas = canvasRef.value
  const context = canvas?.getContext('2d')
  if (!canvas || !context) return
  const rect = canvas.getBoundingClientRect()
  context.clearRect(0, 0, rect.width, rect.height)

  for (const particle of particles) {
    particle.x += particle.vx
    particle.y += particle.vy
    if (particle.y < -10) particle.y = rect.height + 10
    if (particle.x < -10) particle.x = rect.width + 10
    if (particle.x > rect.width + 10) particle.x = -10
    context.beginPath()
    context.fillStyle = `rgba(72, 116, 126, ${particle.alpha})`
    context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2)
    context.fill()
  }

  for (let i = 0; i < particles.length; i += 1) {
    for (let j = i + 1; j < particles.length; j += 1) {
      const a = particles[i]
      const b = particles[j]
      const distance = Math.hypot(a.x - b.x, a.y - b.y)
      if (distance > 92) continue
      context.beginPath()
      context.strokeStyle = `rgba(76, 122, 132, ${(1 - distance / 92) * 0.07})`
      context.lineWidth = 0.6
      context.moveTo(a.x, a.y)
      context.lineTo(b.x, b.y)
      context.stroke()
    }
  }
  frame = window.requestAnimationFrame(draw)
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(canvas)
  resize()
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) draw()
})

onUnmounted(() => {
  window.cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
})
</script>

<template>
  <canvas ref="canvasRef" class="ink-ambient" aria-hidden="true" />
</template>

<style scoped>
.ink-ambient {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}
</style>
