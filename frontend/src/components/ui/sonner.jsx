import { Toaster as Sonner, toast } from "sonner"

const Toaster = ({
  ...props
}) => {
  return (
    <Sonner
      theme="light"
      position="bottom-right"
      icons={{}}
      toastOptions={{
        unstyled: false,
        classNames: {
          toast: "zz-toast",
          title: "zz-toast-title",
          description: "zz-toast-desc",
          actionButton: "zz-toast-action",
          cancelButton: "zz-toast-cancel",
          closeButton: "zz-toast-close",
          success: "zz-toast-success",
          error: "zz-toast-error",
          warning: "zz-toast-warning",
          info: "zz-toast-info",
        },
      }}
      {...props} />
  );
}

export { Toaster, toast }
