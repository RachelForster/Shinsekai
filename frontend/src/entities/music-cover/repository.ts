import { getPlatform } from "../../shared/platform/platform";
import type {
  MusicCoverConfigInput,
  MusicCoverConfigResult,
  MusicCoverRunInput,
  MusicCoverRunResult,
  MusicCoverSearchResult,
  MusicCoverSource,
  TaskProgressOptions,
} from "../../shared/platform/types";

export function saveMusicCoverConfig(input: MusicCoverConfigInput): Promise<MusicCoverConfigResult> {
  return getPlatform().musicCover.saveConfig(input);
}

export function searchMusicCover(input: { query: string; source: MusicCoverSource }): Promise<MusicCoverSearchResult> {
  return getPlatform().musicCover.search(input);
}

export function runMusicCover(
  input: MusicCoverRunInput,
  options?: TaskProgressOptions<MusicCoverRunResult>,
): Promise<MusicCoverRunResult> {
  return getPlatform().musicCover.run(input, options);
}
