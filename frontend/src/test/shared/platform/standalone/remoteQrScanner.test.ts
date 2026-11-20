import { afterEach, describe, expect, it, vi } from "vitest";

import {
  decodeQrFromCanvas,
  hasQrDecodeCapability,
  isLoopbackHostname,
  parseRemoteBridgeQrPayload,
} from "../../../../features/runtime-mode/remoteQrScanner";

describe("remoteQrScanner", () => {
  afterEach(() => {
    delete window.BarcodeDetector;
    delete window.__SHINSEKAI_ANDROID_QR__;
    vi.restoreAllMocks();
  });

  it("parses official Desktop MobileAccessTransport QR URL with bridge token", () => {
    expect(parseRemoteBridgeQrPayload("http://192.168.1.88:8789/?shinsekai_bridge_token=abcdef012345#/chat")).toEqual({
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

    expect(parseRemoteBridgeQrPayload("http://192.168.1.88:8789/#/chat?shinsekai_bridge_token=hashTok")).toEqual({
      url: "http://192.168.1.88:8789",
      token: "hashTok",
    });

    expect(parseRemoteBridgeQrPayload("shinsekai://connect?url=http%3A%2F%2F10.0.0.5%3A8787&token=schemeTok")).toEqual({
      url: "http://10.0.0.5:8787",
      token: "schemeTok",
    });

    expect(parseRemoteBridgeQrPayload('{"url":"http://192.168.31.9:8787/","token":"t1"}')).toEqual({
      url: "http://192.168.31.9:8787",
      token: "t1",
    });

    expect(parseRemoteBridgeQrPayload('{"host":"192.168.31.9","port":8787,"authToken":"t2"}')).toEqual({
      url: "http://192.168.31.9:8787",
      token: "t2",
    });

    expect(parseRemoteBridgeQrPayload("192.168.1.50:8789")).toEqual({
      url: "http://192.168.1.50:8789",
      token: "",
    });
  });

  it("rejects full loopback IPv4/IPv6 ranges, IPv4-mapped IPv6 loopback, and invalid payloads while allowing LAN IPv6", () => {
    expect(() => parseRemoteBridgeQrPayload("   ")).toThrow("未识别到二维码内容");
    for (const loopbackPayload of [
      "http://127.0.0.1:8787/?shinsekai_bridge_token=x",
      "http://127.0.0.2:8787",
      "http://127.255.255.254:8787",
      "127.0.1.1:8789",
      "http://127.1:8787",
      "http://0.0.0.0:8787",
      "http://localhost:8787",
      "http://sub.localhost:8787",
      "http://[::1]:8787",
      "[::1]:8787",
      "http://[::ffff:127.0.0.1]:8787",
      "http://[::ffff:127.0.0.2]:8787",
      "http://[0:0:0:0:0:ffff:127.255.0.1]:8787",
      '{"host":"127.0.0.2","port":8787}',
      "https://example.org/?shinsekai_bridge=http%3A%2F%2F127.0.0.2%3A8787",
    ]) {
      expect(() => parseRemoteBridgeQrPayload(loopbackPayload), loopbackPayload).toThrow("本机回环地址");
    }

    expect(isLoopbackHostname("[::ffff:7f00:2]")).toBe(true);
    expect(isLoopbackHostname("[::ffff:0:127.0.0.2]")).toBe(true);
    expect(isLoopbackHostname("::127.0.0.1")).toBe(true);
    expect(isLoopbackHostname("[::ffff:192.168.1.88]")).toBe(false);
    expect(isLoopbackHostname("192.168.1.88")).toBe(false);

    expect(parseRemoteBridgeQrPayload("http://[::ffff:192.168.1.88]:8787/?shinsekai_bridge_token=v6tok")).toEqual({
      url: "http://[::ffff:c0a8:158]:8787",
      token: "v6tok",
    });

    expect(() => parseRemoteBridgeQrPayload("not-a-valid-qr")).toThrow("有效的新世界电脑端连接地址");
    expect(() => parseRemoteBridgeQrPayload("ftp://192.168.1.5:21")).toThrow("有效的新世界电脑端连接地址");
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
    await expect(decodeQrFromCanvas(canvas)).resolves.toBe("http://192.168.1.9:8787/?shinsekai_bridge_token=fallback");
    expect(androidDecodeMock).toHaveBeenCalledWith("data:image/jpeg;base64,ZmFrZQ==");
  });
});
