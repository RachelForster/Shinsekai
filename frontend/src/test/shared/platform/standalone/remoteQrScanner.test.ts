import { afterEach, describe, expect, it, vi } from "vitest";

import {
  decodeQrFromCanvas,
  hasQrDecodeCapability,
  parseRemoteBridgeQrPayload,
} from "../../../../features/runtime-mode/remoteQrScanner";

describe("remoteQrScanner", () => {
  afterEach(() => {
    delete window.BarcodeDetector;
    delete window.__SHINSEKAI_ANDROID_QR__;
    vi.restoreAllMocks();
  });

  it("parses official Desktop MobileAccessTransport QR URL with bridge token", () => {
    expect(
      parseRemoteBridgeQrPayload(
        "http://192.168.1.88:8789/?shinsekai_bridge_token=abcdef012345#/chat",
      ),
    ).toEqual({
      url: "http://192.168.1.88:8789",
      token: "abcdef012345",
    });
  });

  it("parses explicit shinsekai_bridge, hash query, shinsekai://, JSON, and bare host:port formats", () => {
    expect(
      parseRemoteBridgeQrPayload(
        "https://example.org/entry?shinsekai_bridge=http%3A%2F%2F192.168.10.22%3A8787%2F&shinsekai_bridge_token=tok-a",
      ),
    ).toEqual({
      url: "http://192.168.10.22:8787",
      token: "tok-a",
    });

    expect(
      parseRemoteBridgeQrPayload("http://192.168.1.88:8789/#/chat?shinsekai_bridge_token=hashTok"),
    ).toEqual({
      url: "http://192.168.1.88:8789",
      token: "hashTok",
    });

    expect(
      parseRemoteBridgeQrPayload(
        "shinsekai://connect?url=http%3A%2F%2F10.0.0.5%3A8787&token=schemeTok",
      ),
    ).toEqual({
      url: "http://10.0.0.5:8787",
      token: "schemeTok",
    });

    expect(
      parseRemoteBridgeQrPayload('{"url":"http://192.168.31.9:8787/","token":"t1"}'),
    ).toEqual({
      url: "http://192.168.31.9:8787",
      token: "t1",
    });

    expect(
      parseRemoteBridgeQrPayload('{"host":"192.168.31.9","port":8787,"authToken":"t2"}'),
    ).toEqual({
      url: "http://192.168.31.9:8787",
      token: "t2",
    });

    expect(parseRemoteBridgeQrPayload("192.168.1.50:8789")).toEqual({
      url: "http://192.168.1.50:8789",
      token: "",
    });
  });

  it("rejects loopback URLs and invalid or empty payloads with actionable errors", () => {
    expect(() => parseRemoteBridgeQrPayload("   ")).toThrow("未识别到二维码内容");
    expect(() =>
      parseRemoteBridgeQrPayload("http://127.0.0.1:8787/?shinsekai_bridge_token=x"),
    ).toThrow("本机回环地址");
    expect(() => parseRemoteBridgeQrPayload("http://localhost:8787")).toThrow("本机回环地址");
    expect(() => parseRemoteBridgeQrPayload("not-a-valid-qr")).toThrow("有效的新世界电脑端连接地址");
    expect(() => parseRemoteBridgeQrPayload("ftp://192.168.1.5:21")).toThrow(
      "有效的新世界电脑端连接地址",
    );
  });

  it("prefers BarcodeDetector when available and falls back to Android ZXing bridge otherwise", async () => {
    expect(hasQrDecodeCapability()).toBe(false);

    const canvas = document.createElement("canvas");
    vi.spyOn(canvas, "toDataURL").mockReturnValue("data:image/jpeg;base64,ZmFrZQ==");

    const detectMock = vi.fn().mockResolvedValue([{ rawValue: "http://192.168.1.9:8789" }]);
    class MockBarcodeDetector {
      static async getSupportedFormats() {
        return ["qr_code"];
      }
      detect = detectMock;
    }
    const androidDecodeMock = vi.fn(() => "http://192.168.1.9:8787/?shinsekai_bridge_token=fallback");

    window.BarcodeDetector = MockBarcodeDetector as unknown as Window["BarcodeDetector"];
    window.__SHINSEKAI_ANDROID_QR__ = { decodeImageDataUrl: androidDecodeMock };
    expect(hasQrDecodeCapability()).toBe(true);

    await expect(decodeQrFromCanvas(canvas)).resolves.toBe("http://192.168.1.9:8789");
    expect(detectMock).toHaveBeenCalledTimes(1);
    expect(androidDecodeMock).not.toHaveBeenCalled();

    // When BarcodeDetector throws or returns empty, falls back seamlessly to Android ZXing bridge
    detectMock.mockRejectedValueOnce(new Error("detector failure"));
    await expect(decodeQrFromCanvas(canvas)).resolves.toBe(
      "http://192.168.1.9:8787/?shinsekai_bridge_token=fallback",
    );
    expect(androidDecodeMock).toHaveBeenCalledWith("data:image/jpeg;base64,ZmFrZQ==");
  });
});
