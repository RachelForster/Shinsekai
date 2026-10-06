import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { BackgroundLayer, SpriteLayer } from "../../src/features/chat-stage/components/StageLayers";
import { I18nProvider } from "../../src/shared/i18n/I18nProvider";
import { ImageAssetGallery, VisualMedia } from "../../src/shared/ui";
import "../../src/features/chat-stage/styles/media-layers.css";

const video = `${location.origin}/api/media?path=happy.MP4&token=test`;
const image =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="128"><rect width="64" height="128" fill="pink"/></svg>',
  );

function Fixture() {
  const [hidden, setHidden] = useState(false);
  const [showVideo, setShowVideo] = useState(true);
  const [broken, setBroken] = useState(false);
  const source = showVideo ? video : image;
  return (
    <>
      <button onClick={() => setHidden(!hidden)}>{hidden ? "Show layers" : "Hide layers"}</button>
      <button onClick={() => setShowVideo(!showVideo)}>{showVideo ? "Use image" : "Use MP4"}</button>
      <button onClick={() => setBroken(!broken)}>{broken ? "Restore preview" : "Break preview"}</button>
      <main>
        <div id="background" className="panel">
          <BackgroundLayer path={source} hidden={hidden} transparent={false} />
        </div>
        <div id="sprite" className="panel">
          <SpriteLayer
            hidden={hidden}
            sprites={[{ id: "happy", label: "Happy", avatarType: "static", modelUrl: "", path: source }]}
            runtimeScaleForSprite={() => 1}
            runtimeFramingForSprite={() => ({ heightRatio: 0.5, verticalPosition: 0 })}
          />
        </div>
        <div id="preview" className="panel">
          <VisualMedia
            alt="Preview"
            errorMessage="Check the H.264 MP4 file."
            src={broken ? `${location.origin}/api/media?path=broken.mp4` : video}
          />
        </div>
        <div id="covers">
          <ImageAssetGallery
            items={[
              { id: "video", title: "happy.MP4", videoSrc: video },
              { id: "image", title: "idle.png", imageSrc: image },
            ]}
            selectedIndex={0}
            onSelect={() => {}}
          />
        </div>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider language="en">
      <Fixture />
    </I18nProvider>
  </StrictMode>,
);
