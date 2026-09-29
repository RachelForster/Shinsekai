import type { AvatarFormat } from "../entities/character-visual/contracts";
import { registerAvatarFormat } from "../entities/character-visual/registry";

// Descriptors stay lightweight: format.ts exports metadata and a dynamic load().
// Only formats shipped in this frontend build are registered here.
const descriptors = import.meta.glob<AvatarFormat<unknown, unknown>>(
  "../entities/character-visual/adapters/*/format.ts",
  { eager: true, import: "default" },
);

for (const descriptor of Object.values(descriptors)) {
  registerAvatarFormat(descriptor);
}
