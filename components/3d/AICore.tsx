"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Icosahedron, MeshDistortMaterial, Sphere, Wireframe } from "@react-three/drei";
import * as THREE from "three";

export function AICore({ fast = false }) {
  const groupRef = useRef<THREE.Group>(null);
  const coreRef = useRef<THREE.Mesh>(null);
  
  const speedMultiplier = fast ? 3 : 1;

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.x = state.clock.elapsedTime * 0.2 * speedMultiplier;
      groupRef.current.rotation.y = state.clock.elapsedTime * 0.3 * speedMultiplier;
    }
    if (coreRef.current) {
      coreRef.current.rotation.y = -state.clock.elapsedTime * 0.5 * speedMultiplier;
    }
  });

  return (
    <group ref={groupRef}>
      <ambientLight intensity={0.5} />
      <directionalLight position={[2, 2, 5]} intensity={2} color="#818cf8" />
      <pointLight position={[-2, -2, -5]} intensity={1} color="#a78bfa" />
      
      {/* Outer pulsing wireframe */}
      <Sphere args={[1.6, 16, 16]}>
        <meshBasicMaterial color="#38bdf8" wireframe transparent opacity={0.15} />
      </Sphere>

      {/* Inner distorting core */}
      <Icosahedron ref={coreRef} args={[1.2, 4]}>
        <MeshDistortMaterial 
          color="#4f46e5" 
          emissive="#312e81"
          emissiveIntensity={1}
          clearcoat={1}
          clearcoatRoughness={0.2}
          roughness={0.2}
          metalness={0.8}
          distort={fast ? 0.6 : 0.4} 
          speed={fast ? 4 : 2} 
        />
      </Icosahedron>

      {/* Floating particles around core */}
      <Sphere args={[2, 8, 8]}>
         <pointsMaterial size={0.05} color="#c084fc" transparent opacity={0.6} />
      </Sphere>
    </group>
  );
}
