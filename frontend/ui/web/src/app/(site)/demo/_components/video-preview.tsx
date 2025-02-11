import DemoContext from "../hooks/createDemoContext";
import { useContext } from "react";

export default function VideoPreview() {
  const {
    selectedFiles: [videoFile],
  } = useContext(DemoContext)!;
  return (
    <>
      <video className="w-[400px] sm:w-[600px] lg:w-[800px]" controls>
        <source src={URL.createObjectURL(videoFile!)} type={videoFile!.type} />
        Your browser does not support the video tag.
      </video>
    </>
  );
}
