'use client'

import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  maxLife: number
  size: number
}

interface FireCanvasProps {
  active: boolean
  width: number
  height: number
}

export function FireCanvas({ active, width, height }: FireCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const particlesRef = useRef<Particle[]>([])
  const animFrameRef = useRef<number>(0)
  const activeRef = useRef(active)
  const globalAlphaRef = useRef(0)

  activeRef.current = active

  useEffect(() => {
    if (active) {
      globalAlphaRef.current = 1
    } else {
      const fadeInterval = setInterval(() => {
        globalAlphaRef.current -= 0.035
        if (globalAlphaRef.current <= 0) {
          globalAlphaRef.current = 0
          clearInterval(fadeInterval)
        }
      }, 28)
      return () => clearInterval(fadeInterval)
    }
  }, [active])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    function spawnParticle() {
      if (!canvas) return
      const spread = canvas.width * 0.55
      const cx = canvas.width / 2
      const x = cx + (Math.random() - 0.5) * spread
      const maxLife = 50 + Math.random() * 50
      particlesRef.current.push({
        x,
        y: canvas.height,
        vx: (Math.random() - 0.5) * 0.9,
        vy: -(1.2 + Math.random() * 2.2),
        life: maxLife,
        maxLife,
        size: 2 + Math.random() * 4.5,
      })
    }

    function getColor(age: number): string {
      if (age < 0.25) {
        const t = age / 0.25
        const r = Math.round(200 + t * 30)
        const g = Math.round(60 - t * 20)
        const b = 0
        return `rgb(${r},${g},${b})`
      } else if (age < 0.55) {
        const t = (age - 0.25) / 0.3
        const r = Math.round(230 - t * 90)
        const g = Math.round(40 - t * 35)
        const b = 0
        return `rgb(${r},${g},${b})`
      } else {
        const t = (age - 0.55) / 0.45
        const v = Math.round(140 - t * 110)
        return `rgb(${v},${Math.round(v * 0.2)},0)`
      }
    }

    function draw() {
      if (!canvas || !ctx) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const ga = Math.max(0, globalAlphaRef.current)

      if (activeRef.current && ga > 0) {
        const spawnRate = 2 + Math.round(ga * 2)
        for (let i = 0; i < spawnRate; i++) spawnParticle()
      }

      particlesRef.current = particlesRef.current.filter(p => p.life > 0)

      for (const p of particlesRef.current) {
        const age = 1 - p.life / p.maxLife
        const particleAlpha = age < 0.15
          ? (age / 0.15)
          : (1 - ((age - 0.15) / 0.85))
        const alpha = particleAlpha * ga * 0.72
        if (alpha <= 0) { p.life--; continue }

        const size = p.size * (1 - age * 0.55)
        const color = getColor(age)

        ctx.save()
        ctx.globalAlpha = alpha

        const glowSize = size * (age < 0.4 ? 3.5 : 1.8)
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowSize)
        grad.addColorStop(0, color)
        grad.addColorStop(1, 'transparent')
        ctx.beginPath()
        ctx.arc(p.x, p.y, glowSize, 0, Math.PI * 2)
        ctx.fillStyle = grad
        ctx.fill()

        ctx.beginPath()
        ctx.arc(p.x, p.y, size * 0.5, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()

        ctx.restore()

        const turbulence = 0.3 + age * 0.5
        p.x += p.vx + (Math.random() - 0.5) * turbulence
        p.y += p.vy
        p.vy *= 0.985
        p.life--
      }

      animFrameRef.current = requestAnimationFrame(draw)
    }

    animFrameRef.current = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(animFrameRef.current)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ display: 'block', pointerEvents: 'none' }}
    />
  )
}
